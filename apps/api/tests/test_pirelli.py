"""Pirelli contracts: real excerpts and explicit synthetic fault injection."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

from tire_api.adapters import pirelli
from tire_api.domain import VariantInput

FIXTURES = Path(__file__).parent / "fixtures" / "brand_sources"
QUERY = {"model": "P ZERO (PZ4)", "size": "265/40R20"}


def excerpt(rim=20):
    return (FIXTURES / f"pirelli-pz4-265-40-r{rim}-excerpt.html").read_text(encoding="utf-8")


def payload(rim=20):
    # Fixture transformation is documented separately from production parsing.
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", excerpt(rim), re.S)
    product = json.loads(scripts[0])
    literal = scripts[1].removeprefix("self.__next_f.push(").removesuffix(")")
    flight = json.loads(literal)[1]
    props = json.loads(flight.split(":", 1)[1])[3]
    return deepcopy(props), deepcopy(product)


def body(props=None, product=None, *, record="ac", prefix="", extra=""):
    if props is None:
        props, original_product = payload()
        product = original_product if product is None else product
    if product is None:
        product = payload()[1]
    def encoded(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    flight = prefix + record + ":" + encoded(["$", "$L99", None, props]) + "\n" + extra
    return ('<html><body><script type="application/ld+json">' + encoded(product)
            + "</script><script>self.__next_f.push(" + encoded([1, flight]) + ")</script></body></html>")


def test_real_20_rows_have_exact_distinct_codes_gtins_oe_and_explicit_technologies():
    rows = pirelli.parse_html(excerpt(), QUERY)
    assert [row["manufacturer_product_code"] for row in rows] == ["2524000", "4080500", "4159300"]
    assert [row["facts"]["gtin"] for row in rows] == ["8019227252408", "8019227408058", "8019227415933"]
    assert [row["size"] for row in rows] == ["265/40R20", "265/40R20", "265/40ZR20"]
    assert [row["oe_mark"] for row in rows] == ["AO", "RE0", "MO1"]
    assert [row["acoustic_technology"] for row in rows] == ["PNCS", None, "PNCS"]
    assert [row["facts"]["pncs"] for row in rows] == [True, False, True]
    assert [row["facts"]["elect"] for row in rows] == [False, True, True]
    assert [row["facts"]["ev_marketing_mark"] for row in rows] == [False, True, True]
    assert [row["run_flat"] for row in rows] == [False, True, False]
    assert rows[1]["facts"]["technology_features"] == ["ELECT", "RUNFLAT"]
    assert rows[2]["facts"]["technology_features"] == ["PNCS", "ELECT"]
    for index, row in enumerate(rows):
        validated = VariantInput.model_validate(row)
        assert (validated.brand, validated.model, validated.region) == ("Pirelli", "P ZERO (PZ4)", "US")
        assert row["xl"] is True and row["hl"] is None
        assert row["facts"]["evidence_spans"]["manufacturer_product_code"] == f"NextFlight.mainProps.sizeList.ipcodes[{index}].id"
        assert row['facts']['product_code_type'] == 'IP_CODE'
        assert validated.identity()['product_code_type'] == 'IP_CODE'
        assert row['facts']['evidence_spans']['facts.product_code_type'] == f'NextFlight.mainProps.sizeList.ipcodes[{index}].id'
        assert row["facts"]["evidence_spans"]["facts.ev_marketing_mark"].endswith(".elect")
    assert len({VariantInput.model_validate(row).identity_key("pirelli-us", "q", i)[0]
                for i, row in enumerate(rows)}) == 3


def test_real_21_preserves_parenthesized_y_and_equal_displayed_skus():
    rows = pirelli.parse_html(excerpt(21), {"model": pirelli.MODEL, "size": "265/40ZR21"})
    assert len(rows) == 8
    assert [row["manufacturer_product_code"] for row in rows[:2]] == ["2679200", "3768200"]
    assert [(row["load_index"], row["speed_rating"], row["size"]) for row in rows[:2]] == [
        ("105", "(Y)", "265/40ZR21"), ("105", "(Y)", "265/40ZR21")]
    assert [row["manufacturer_product_code"] for row in rows[2:4]] == ["3791000", "3973300"]
    assert rows[2]["source_variant_name"] == rows[3]["source_variant_name"]
    assert VariantInput.model_validate(rows[2]).identity() != VariantInput.model_validate(rows[3]).identity()
    for row in rows:
        VariantInput.model_validate(row)


def test_real_anomalous_utqg_never_swaps_components_or_emits_canonical_triple():
    for row in pirelli.parse_html(excerpt(), QUERY):
        facts = row["facts"]
        assert facts["source_utqg_raw"] in {"220/A/AA", "280/A/AA"}
        assert facts["source_utqg_components"]["traction"] == "A"
        assert facts["source_utqg_components"]["temperature"] == "AA"
        assert not {"utqg_treadwear", "utqg_traction", "utqg_temperature"} & facts.keys()
        assert facts["source_field_anomalies"] == [{
            "field": "utqg_temperature", "raw_value": "AA",
            "reason": "source_temperature_outside_standard_enum",
            "locator": facts["evidence_spans"]["facts.source_utqg_components"] + ".temperature"}]


def test_missing_optional_declarations_remain_unknown_despite_model_marketing():
    props, product = payload()
    props["pageJson"]["tyre_info"]["techs"] = [{"technology": "pncs"}, {"technology": "elect"}, {"technology": "runflat"}]
    for row in props["sizeList"]["ipcodes"]:
        for field in ("pncs", "elect", "run_flat", "is-xl", "ean_code", "marking", "techs", "techEnums", "technologies"):
            row.pop(field, None)
        for field in ("load", "oe_marking", "utqg", "treadwear", "traction", "temperature"):
            row["ipcodeTechSpec"].pop(field, None)
    rows = pirelli.parse_html(body(props, product), QUERY)
    for row in rows:
        for field in ("xl", "hl", "oe_mark", "acoustic_technology", "run_flat"):
            assert row[field] is None
        assert not {"pncs", "elect", "ev_marketing_mark", "gtin", "technology_features", "source_utqg_raw"} & row["facts"].keys()


def test_explicit_hl_and_valid_utqg_use_only_row_declarations():
    props, product = payload()
    for row in props["sizeList"]["ipcodes"]:
        row.pop("is-xl")
        row["ipcodeTechSpec"].update(load="HL", utqg="280/AA/A", treadwear="280", traction="AA", temperature="A")
    rows = pirelli.parse_html(body(props, product), QUERY)
    assert all(row["hl"] is True and row["xl"] is None for row in rows)
    assert all(row["facts"]["utqg_temperature"] == "A" and row["facts"]["utqg_traction"] == "AA" for row in rows)
    assert all("source_field_anomalies" not in row["facts"] for row in rows)


@pytest.mark.parametrize("field,value", [
    ("id", "bad"), ("id", None), ("ean_code", "8019227252409"), ("ean_code", 8019227252408),
    ("description", "265/40R21 104Y"), ("structure", "ZR"), ("rim", "20"),
    ("load_speed_rating", "104FAST"), ("load_speed_rating", "104W"),
    ("productId", "pzerocar"), ("pncs", "true"), ("run_flat", 0),
    ("techEnums", []), ("marking", "OTHER"), ("is-xl", False),
    ("search-description", "225/45R18"), ("section-with", "264"), ("serie", "45"),
])
def test_damage_in_any_row_rejects_the_complete_collection(field, value):
    props, product = payload()
    props["sizeList"]["ipcodes"][0][field] = value
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


@pytest.mark.parametrize("field,value", [("ipcode", "9999999"), ("productName", "P-ZERO"),
    ("load", "EXTRA"), ("lsi", "105"), ("speed", "W 270 (km/h)"), ("oe_marking", "OTHER")])
def test_conflicting_technical_spec_rejects_all_rows(field, value):
    props, product = payload()
    props["sizeList"]["ipcodes"][1]["ipcodeTechSpec"][field] = value
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


def test_duplicate_codes_gtins_props_and_json_keys_fail_closed():
    props, product = payload()
    props["sizeList"]["ipcodes"].append(deepcopy(props["sizeList"]["ipcodes"][0]))
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)
    props, product = payload()
    props["sizeList"]["ipcodes"][1]["ean_code"] = props["sizeList"]["ipcodes"][0]["ean_code"]
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)
    props, product = payload()
    extra = "bd:" + json.dumps(["$", "$L2", None, props]) + "\n"
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product, extra=extra), QUERY)
    duplicate = body(props, product).replace('\\"id\\":\\"2524000\\"', '\\"id\\":\\"2524000\\",\\"id\\":\\"2524000\\"', 1)
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(duplicate, QUERY)


@pytest.mark.parametrize("mutation", ["region", "language", "generation", "scope", "search_scope", "details", "brand", "jsonld_model", "empty", "pagination"])
def test_foreign_or_incomplete_page_scope_is_not_an_empty_result(mutation):
    props, product = payload()
    if mutation == "region": props["genericSettings"]["country"] = "GB"
    if mutation == "language": props["genericSettings"]["lang"] = "en-gb"
    if mutation == "generation": props["pageJson"]["tyre_info"]["productName"] = "P ZERO"
    if mutation == "scope": props["querySize"] = "265_40-r21"
    if mutation == "search_scope": props["searchParams"]["size"] = "265_40-r21"
    if mutation == "details": props["queryDetails"] = "104y-xl-audi-pncs"
    if mutation == "brand": product["brand"]["name"] = "Other"
    if mutation == "jsonld_model": product["name"] = "P ZERO (PZ5)"
    if mutation == "empty": props["sizeList"]["ipcodes"] = []
    if mutation == "pagination": props["sizeList"]["hasMore"] = True
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


@pytest.mark.parametrize("nested", [False, True], ids=["collection-root", "nested-metadata-list"])
@pytest.mark.parametrize("field,value", [
    ("has_more", True), ("has-more", False), ("hasMore", None),
    ("cursor", "next"), ("next_page", "page2"), ("nextPage", None),
    ("PAGE", 1), ("page_number", 1), ("offset", 0), ("limit", 3),
    ("total", 30), ("total_count", 30), ("totalPages", 2),
    ("truncated", True), ("is_truncated", False), ("partial", False),
    ("pagination", None),
])
def test_collection_pagination_and_truncation_drift_rejects_all_rows(field, value, nested):
    props, product = payload()
    if nested:
        props["sizeList"]["metadata"] = {"checkpoints": [{field: value}]}
    else:
        props["sizeList"][field] = value
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


def test_collection_drift_check_does_not_scan_model_marketing_metadata():
    props, product = payload()
    props["pageJson"]["tyre_info"]["marketing"] = {"pagination": {"has_more": True}, "total": 139}
    assert pirelli.parse_html(body(props, product), QUERY) == pirelli.parse_html(excerpt(), QUERY)


@pytest.mark.parametrize("row_index,technologies", [
    (0, ["ELECT&trade;"]), (1, ["ELECT&trade;"]), (2, ["PNCS&trade;"]),
])
def test_conflicting_displayed_row_technologies_rejects_all_rows(row_index, technologies):
    props, product = payload()
    props["sizeList"]["ipcodes"][row_index]["technologies"] = technologies
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


@pytest.mark.parametrize("technologies", [
    None, {}, "PNCS&trade;", [None], [True], [{"name": "PNCS"}],
    [""], ["&trade;"], ["PNCS&trade;"] * 31,
])
def test_malformed_displayed_row_technologies_rejects_all_rows(technologies):
    props, product = payload()
    props["sizeList"]["ipcodes"][0]["technologies"] = technologies
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


def test_displayed_row_technologies_normalize_entities_trademarks_and_whitespace():
    props, product = payload()
    for row, technologies in zip(props["sizeList"]["ipcodes"], [
        [" pncs &#8482; "], ["  RUN \t\n FLAT  ", " \n elecT&trade; \n "], [" \tPNCS™  ", "ELECT™"],
    ]):
        row["technologies"] = technologies
    assert pirelli.parse_html(body(props, product), QUERY) == pirelli.parse_html(excerpt(), QUERY)


def test_displayed_row_technologies_do_not_fill_missing_boolean_declarations():
    props, product = payload()
    for row in props["sizeList"]["ipcodes"]:
        for field in ("pncs", "elect", "run_flat"):
            row.pop(field)
    for row in pirelli.parse_html(body(props, product), QUERY):
        assert row["acoustic_technology"] is None and row["run_flat"] is None
        assert not {"pncs", "elect", "ev_marketing_mark", "technology_features"} & row["facts"].keys()


def test_flight_text_lengths_are_bytes_record_ids_not_fixed_and_scripts_never_execute(tmp_path):
    marker = tmp_path / "must-not-exist"
    malicious = '<script>require("fs").writeFileSync(' + json.dumps(str(marker)) + ',"bad");throw Error("never execute")</script>'
    prefix_text = "字😀"
    prefix = f"f0:T{len(prefix_text.encode('utf-8')):x}," + prefix_text + ':HL["/resource","style"]\n'
    parsed = pirelli.parse_html(malicious + body(record="ba", prefix=prefix), QUERY)
    assert len(parsed) == 3 and not marker.exists()
    expression = '<script>self.__next_f.push([1,(()=>{require("fs").writeFileSync("bad","bad");return "x"})()])</script>'
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(expression, QUERY)
    assert not marker.exists()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_is_rejected_even_in_unused_source_fields(value):
    props, product = payload()
    props["sizeList"]["unused"] = "NUMBER_CANARY"
    damaged = body(props, product).replace('\\"NUMBER_CANARY\\"', value)
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(damaged, QUERY)


def test_bounds_truncated_text_duplicate_record_and_deep_json_fail_closed():
    for captured in ("<html>challenge</html>", excerpt() + "x" * pirelli.MAX_BODY_BYTES,
                     body(prefix="f:Tffffff,short"), body(extra='ac:"duplicate"\n')):
        with pytest.raises(ValueError, match="^parser_schema_changed$"):
            pirelli.parse_html(captured, QUERY)
    props, product = payload()
    deep = "bottom"
    for _ in range(pirelli.MAX_DEPTH + 1): deep = [deep]
    props["sizeList"]["unused"] = deep
    with pytest.raises(ValueError, match="^parser_schema_changed$"):
        pirelli.parse_html(body(props, product), QUERY)


def test_query_url_is_metric_dimension_only_and_errors_are_safe():
    assert pirelli.build_query_url(QUERY) == pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20"
    assert pirelli.build_query_url({"size": "265 / 40 ZR20"}) == pirelli.build_query_url(QUERY)
    for query, reason in [({"model": pirelli.MODEL}, "source_size_required"),
                          ({"size": "bad"}, "invalid_size"), ({"size": []}, "invalid_size"),
                          ({"model": "P ZERO", "size": "265/40R20"}, "unsupported_model")]:
        with pytest.raises(ValueError, match="^" + reason + "$"):
            pirelli.build_query_url(query)


@pytest.mark.parametrize("url", [
    pirelli.ORIGIN + pirelli.BASE_PATH, pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20/104y-xl-audi-pncs",
    pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20?ipcode=2524000",
    pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20?", pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20#",
    pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20/", pirelli.ORIGIN + pirelli.BASE_PATH + "/999_40-r20",
    pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-zr20", pirelli.ORIGIN + pirelli.BASE_PATH + "/265_40-r20%2fdetails",
    "https://user@www.pirelli.com" + pirelli.BASE_PATH + "/265_40-r20",
    "https://www.pirelli.com:444" + pirelli.BASE_PATH + "/265_40-r20",
    "https://www.pirelli.com.evil.test" + pirelli.BASE_PATH + "/265_40-r20",
    "http://www.pirelli.com" + pirelli.BASE_PATH + "/265_40-r20",
])
def test_permitted_path_rejects_navigation_queries_details_and_other_origins(url):
    assert not pirelli.permitted_path(url)


def test_permitted_path_accepts_only_exact_valid_fixed_dimensions():
    assert pirelli.permitted_path(pirelli.build_query_url(QUERY))
    assert pirelli.permitted_path("https://www.pirelli.com:443" + pirelli.BASE_PATH + "/265_40-r21")
    assert pirelli.permitted_path(pirelli.ORIGIN + pirelli.BASE_PATH + "/225_45-r17.5")


def test_real_fixture_provenance_preserves_complete_retained_source_rows():
    manifest = json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8"))
    entries = [entry for entry in manifest["fixtures"] if entry["file"].startswith("pirelli-")]
    assert len(entries) == 2
    for entry in entries:
        raw = (FIXTURES / entry["file"]).read_bytes()
        assert sha256(raw).hexdigest() == entry["fixture_sha256"]
        props, _ = payload(20 if "r20-" in entry["file"] else 21)
        rows = props["sizeList"]["ipcodes"]
        assert [row["id"] for row in rows] == entry["product_codes"]
        assert [sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                for row in rows] == entry["source_row_sha256"]
        assert entry["http_status"] == 200 and entry["source_url"].endswith(props["querySize"])


@pytest.mark.parametrize("name,size,count", [
    ("round31-us-new-p-zero-265-40-r20", "265/40R20", 3),
    ("round31-us-pz4-265-40-r21", "265/40R21", 8),
])
def test_saved_independent_official_capture_replay_when_present(name, size, count):
    root = Path(__file__).resolve().parents[3] / ".artifacts" / "pirelli" / "research"
    capture = root / (name + ".body")
    if not capture.is_file():
        pytest.skip("Independent live source capture unavailable; fixture replay is not a live canary")
    receipt = json.loads((root / (name + ".http.json")).read_text(encoding="utf-8"))
    assert sha256(capture.read_bytes()).hexdigest() == receipt["sha256"]
    rows = pirelli.parse_html(capture.read_text(encoding="utf-8"), {"model": pirelli.MODEL, "size": size})
    assert len(rows) == count
    for row in rows:
        VariantInput.model_validate(row)
