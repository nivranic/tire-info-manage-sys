"""DeviceAIValue AST encoder tests: disambiguation, sample tokens, filters vectors.

Pure tests over the exact parser/encoder layers only: no database, service,
main-app import, env change or network. The projection core stays sealed; these
tests lock the draft-b review gaps E2/E3 (Top1/Top3) at the reference level.
"""
import hashlib
import json

import pytest

from tire_api import device_ai_projection as projection
from tire_api import device_ai_value_encoder as encoder
from tire_api.device_ai_projection import (
    MAX_DEPTH, ProjectionError, canonical_exact_json, exact_digest, parse_exact_json,
)
from tire_api.query_filters import TireFilter, canonical_filters

TOKEN_DTO_FIVE = {"schema": "device-number-token@1", "token": "5"}


def expect_error(code, call):
    with pytest.raises(ProjectionError) as raised:
        call()
    assert raised.value.code == code


def encode(raw: bytes):
    return encoder.encode_source_bytes(raw)


def encoded_number(token: str) -> dict:
    return {"kind": "number", "value": {"schema": "device-number-token@1", "token": token}}


@pytest.mark.parametrize("token", [
    "9007199254740993", "0.1000000000000000001", "-0", "1.2300", "0",
    "1e-5000", "2.5e-3", "1e16", "-9007199254740993", "123456789012345678901234567890",
])
def test_sample_tokens_keep_original_lexeme_and_ast_digest(token):
    raw = ('{"v":' + token + "}").encode()
    value, digest = encode(raw)
    assert value == {"kind": "structured",
                     "fields": [{"name": "v", "value": encoded_number(token)}]}
    assert digest == hashlib.sha256(canonical_exact_json(parse_exact_json(raw))).hexdigest()
    if token == "1.2300":
        # Same binary64 semantics, different archived spelling -> different canonical hash.
        other_value, other_digest = encode(b'{"v":1.23}')
        assert other_value["fields"][0]["value"] == encoded_number("1.23")
        assert digest != other_digest
        assert float(token) == float("1.23")


def test_nonfinite_literals_are_rejected_before_encoding():
    expect_error("device_ai_number_nonfinite", lambda: encode(b'{"v":1e309}'))
    expect_error("device_ai_number_nonfinite", lambda: encode(b'{"v":-1e400}'))
    expect_error("device_ai_number_invalid", lambda: encode(b'{"v":NaN}'))
    expect_error("device_ai_number_invalid", lambda: encode(b'{"v":Infinity}'))
    expect_error("device_ai_number_invalid", lambda: encode(b'{"v":-Infinity}'))


def test_integer_beyond_309_digits_is_legal_and_lossless():
    literal = "9" * 1000
    raw = ('{"v":' + literal + "}").encode()
    value, digest = encode(raw)
    assert value["fields"][0]["value"] == encoded_number(literal)
    assert digest == hashlib.sha256(b'{"v":' + literal.encode() + b"}").hexdigest()
    # Round-trip the DTO through plain JSON without losing the lexeme.
    assert json.loads(json.dumps(value))["fields"][0]["value"]["value"]["token"] == literal


def test_lookalike_object_and_real_number_diverge_both_ways():
    number_tree = encoder.encode_value(parse_exact_json(b"5"))
    object_tree = encoder.encode_value(parse_exact_json(b'{"schema":"device-number-token@1","token":"5"}'))
    assert number_tree == encoded_number("5")
    assert object_tree == {"kind": "structured", "fields": [
        {"name": "schema", "value": {"kind": "text", "value": "device-number-token@1"}},
        {"name": "token", "value": {"kind": "text", "value": "5"}},
    ]}
    assert number_tree != object_tree
    # The sealed core's token_dto collapses both to the same ambiguous shape;
    # the encoder is the layer that must (and does) keep them distinct.
    assert projection.token_dto(parse_exact_json(b"5")) == TOKEN_DTO_FIVE
    assert projection.token_dto(parse_exact_json(b'{"schema":"device-number-token@1","token":"5"}')) == TOKEN_DTO_FIVE
    # Nested positions diverge too: object field values and array items.
    nested_number = encoder.encode_value(parse_exact_json(b'{"a":[5,true,{"token":5}]}'))
    nested_object = encoder.encode_value(parse_exact_json(
        b'{"a":[{"schema":"device-number-token@1","token":"5"},true,{"token":{"schema":"device-number-token@1","token":"5"}}]}'))
    number_item = nested_number["fields"][0]["value"]["items"][0]
    object_item = nested_object["fields"][0]["value"]["items"][0]
    assert number_item["kind"] == "number" and number_item["value"] == TOKEN_DTO_FIVE
    assert object_item["kind"] == "structured"
    assert object_item["fields"][0]["value"] == {"kind": "text", "value": "device-number-token@1"}
    inner = nested_number["fields"][0]["value"]["items"][2]["fields"][0]["value"]
    assert inner == encoded_number("5")
    assert nested_number != nested_object


def test_scalars_null_bool_text_and_nested_structure():
    raw = '{"b":[true,false,null,"","\\u4e2d\\u6587/\\u0001"],"a":{},"z":[[]]}'.encode()
    value, _ = encode(raw)
    assert [field["name"] for field in value["fields"]] == ["a", "b", "z"]  # codepoint-sorted
    assert value == {"kind": "structured", "fields": [
        {"name": "a", "value": {"kind": "structured", "fields": []}},
        {"name": "b", "value": {"kind": "array", "items": [
            {"kind": "boolean", "value": True},
            {"kind": "boolean", "value": False},
            {"kind": "null", "value": None},
            {"kind": "text", "value": ""},
            {"kind": "text", "value": "中文/\u0001"},
        ]}},
        {"name": "z", "value": {"kind": "array", "items": [{"kind": "array", "items": []}]}},
    ]}


def test_encoded_tree_has_no_bare_numbers_and_plain_json_serializable():
    raw = json.dumps({"i": 1, "f": 2.5, "big": 10**30, "s": "t", "arr": [True, None, -0.5],
                      "obj": {"n": 1.23}}, ensure_ascii=False).encode()
    value, _ = encode(raw)

    def only_dto_types(node):
        assert node is None or type(node) in (str, bool, dict, list)
        if type(node) is dict:
            for child in node.values():
                only_dto_types(child)
        elif type(node) is list:
            for child in node:
                only_dto_types(child)

    only_dto_types(value)
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    assert json.loads(text) == value


def test_bare_python_numbers_and_foreign_types_are_rejected():
    for bad in (5, -1, 0.1, float("nan"), b"bytes", {"a": 5}, [1.5], {1: "a"}, object()):
        expect_error("device_ai_value_type_unsupported", lambda bad=bad: encoder.encode_value(bad))


def test_encoder_depth_guard_matches_parser_bound():
    parsed_deep = parse_exact_json(b"[" * MAX_DEPTH + b"0" + b"]" * MAX_DEPTH)
    assert encoder.encode_value(parsed_deep)["kind"] == "array"

    def nest(levels, leaf):
        node = leaf
        for _ in range(levels):
            node = [node]
        return node

    assert encoder.encode_value(nest(MAX_DEPTH, parse_exact_json(b"0")))["kind"] == "array"
    # One level past the parser bound still fails closed on the depth guard,
    # never with a Python recursion error or a silently encoded deep tree.
    expect_error("device_ai_json_depth",
                 lambda: encoder.encode_value(nest(MAX_DEPTH + 1, parse_exact_json(b"0"))))


def test_digest_uses_exact_digest_semantics_with_namespace():
    raw = b'{"v":1.2300}'
    _, plain = encode(raw)
    _, namespaced = encoder.encode_source_bytes(raw, namespace="device-ai-value@1")
    ast = parse_exact_json(raw)
    assert namespaced == exact_digest(ast, namespace="device-ai-value@1")
    assert namespaced != plain
    assert plain == hashlib.sha256(canonical_exact_json(ast)).hexdigest()


def test_source_byte_failures_propagate_from_parser():
    expect_error("device_ai_package_capacity", lambda: encode(b""))
    expect_error("device_ai_json_bom", lambda: encode(b"\xef\xbb\xbf{}"))
    expect_error("device_ai_json_utf8", lambda: encode(b"\xff\xfe{}"))
    expect_error("device_ai_json_duplicate_key", lambda: encode(b'{"a":1,"a":2}'))
    expect_error("device_ai_json_invalid", lambda: encode(b"{"))


FILTERS_SAMPLE = [
    {"field": "brand", "op": "eq", "value": "MICHELIN"},
    {"field": "utqg_treadwear", "op": "gte", "value": 9007199254740993},
    {"field": "eu_external_noise_db", "op": "lte", "value": 68.5},
    {"field": "xl", "op": "eq", "value": True},
    {"field": "size", "op": "eq", "value": "205/55R16"},
    {"field": "run_flat", "op": "is_known"},
]


def canonical_of(conditions):
    return canonical_filters([TireFilter.model_validate(dict(item)) for item in conditions])


def test_filters_exact_json_round_trips_the_server_parser():
    text = encoder.encode_filters_exact_json(FILTERS_SAMPLE)
    assert text.startswith("[") and text.endswith("]")
    assert " " not in text  # compact separators, like the TS stringifyExactJson wire form
    assert '{"field":"brand","op":"eq","value":"michelin"}' in text  # normalized text
    assert '"value":9007199254740993' in text  # bare JSON number, arbitrary precision kept
    assert '"value":68.5' in text and '"value":true' in text
    assert '{"field":"run_flat","op":"is_known"}' in text  # presence op carries no value
    reparsed = [TireFilter.model_validate(item) for item in json.loads(text)]
    assert canonical_filters(reparsed) == canonical_of(FILTERS_SAMPLE)


def test_filters_exact_json_is_deduped_order_stable_and_bounded():
    first = encoder.encode_filters_exact_json(FILTERS_SAMPLE)
    reversed_text = encoder.encode_filters_exact_json(list(reversed(FILTERS_SAMPLE)))
    duplicated = encoder.encode_filters_exact_json(FILTERS_SAMPLE + [dict(FILTERS_SAMPLE[0])])
    assert first == reversed_text == duplicated
    expect_error("device_ai_filters_capacity",
                 lambda: encoder.encode_filters_exact_json([FILTERS_SAMPLE[0]] * 17))
    expect_error("device_ai_filters_capacity", lambda: encoder.encode_filters_exact_json("not-a-list"))


@pytest.mark.parametrize("bad", [
    [{"field": "brand", "op": "eq", "value": float("inf")}],
    [{"field": "utqg_treadwear", "op": "eq", "value": "700"}],
    [{"field": "no_such_field", "op": "eq", "value": "x"}],
    [{"field": "brand", "op": "gte", "value": "x"}],
    [{"field": "run_flat", "op": "is_known", "value": True}],
    [{"field": "xl", "op": "eq", "value": 1}],
    [{"field": "brand", "op": "eq", "value": None}],
    [{"field": "brand", "op": "eq", "value": "x", "extra": 1}],
    [42],
])
def test_filters_exact_json_rejects_non_round_trippable_inputs(bad):
    expect_error("device_ai_filters_invalid", lambda: encoder.encode_filters_exact_json(bad))
