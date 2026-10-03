"""Generate E1 cross-host numeric/canonical vectors (Python reference side).

Reads the vector definitions below, replays every input through the REAL
sealed projection parser and the reference AST encoder, and writes the frozen
expectation file `.artifacts/device-ai50/specs/e1-canonical-vectors-a.json`
consumed by future TS/Rust/Java differential runs and locked by
tests/test_e1_vectors.py (byte-exact replay).

Standalone run (cwd apps/api):
    ./.venv/Scripts/python.exe -B -X utf8 tests/generate_e1_vectors.py

Boundaries: no database, no app import, no network, no git writes; the sealed
`tire_api.device_ai_projection.py` and the reference
`tire_api.device_ai_value_encoder.py` are imported, never modified. Parser
literals are synthetic grammar vectors, not claimed domain facts. Where the
task plan guessed a behavior (e.g. top-level scalars, integer digit bounds),
the recorded value is the parser's REAL behavior, verified at generation time:
any mismatch between the expectation column below and the real function aborts
generation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

RUN = Path(__file__).resolve().parent            # .../apps/api/tests
API_ROOT = RUN.parent                            # .../apps/api
REPO_ROOT = RUN.parents[2]                       # repo root
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from tire_api import device_ai_value_encoder as encoder  # noqa: E402
from tire_api.device_ai_projection import (  # noqa: E402
    MAX_DEPTH, MAX_NODES, MAX_PACKAGE_BYTES, ProjectionError,
    canonical_exact_json, exact_digest, parse_exact_json,
)

OUTPUT = REPO_ROOT / ".artifacts/device-ai50/specs/e1-canonical-vectors-a.json"
PROJECTION_PATH = API_ROOT / "tire_api/device_ai_projection.py"
ENCODER_PATH = API_ROOT / "tire_api/device_ai_value_encoder.py"
SCHEMA = "device-ai-e1-canonical-vectors@1"
NAMESPACE = "device-ai-value@1"  # same namespace string as the encoder tests


def lit(text: str) -> dict:
    """Literal input: the exact JSON source text."""
    return {"form": "literal", "text": text}


def byt(utf8_hex: str) -> dict:
    """Bytes-only input (for byte sequences that are not valid UTF-8 text)."""
    return {"form": "bytes", "utf8_hex": utf8_hex}


def tpl(prefix: str, repeat: str, count: int, suffix: str) -> dict:
    """Template input: prefix + repeat*count + suffix (keeps huge inputs small)."""
    return {"form": "template", "prefix": prefix, "repeat": repeat,
            "count": count, "suffix": suffix}


def expand(inp: dict) -> bytes:
    if inp["form"] == "literal":
        return inp["text"].encode("utf-8")
    if inp["form"] == "bytes":
        return bytes.fromhex(inp["utf8_hex"])
    return (inp["prefix"] + inp["repeat"] * inp["count"] + inp["suffix"]).encode("utf-8")


VECTOR_DEFS = [
    # --- proposal-a.json sample_tokens + encoder-test companions (wrapped form) ---
    dict(id="sample_token_9007199254740993", category="proposal_sample_tokens",
         description="2^53+1：超出 IEEE double 安全整数域，lexeme 原样保留", input=lit('{"v":9007199254740993}')),
    dict(id="sample_token_0_1000000000000000001", category="proposal_sample_tokens",
         description="17 位小数：binary64 不可表示，拼写保留", input=lit('{"v":0.1000000000000000001}')),
    dict(id="sample_token_neg_zero_integer", category="proposal_sample_tokens",
         description="整数负零：保留负号", input=lit('{"v":-0}')),
    dict(id="sample_token_1_2300", category="proposal_sample_tokens",
         description="尾随零保留：与 1.23 同值不同 sha", input=lit('{"v":1.2300}')),
    dict(id="sample_token_1e_minus_5000_underflow", category="proposal_sample_tokens",
         description="源 binary64 下溢为 0.0 但仍有限：接受且保留 lexeme", input=lit('{"v":1e-5000}')),
    dict(id="sample_token_2_5e_minus_3", category="proposal_sample_tokens",
         description="小数科学计数法原样", input=lit('{"v":2.5e-3}')),
    dict(id="sample_token_1e16", category="proposal_sample_tokens",
         description="指数形式不展开为整数", input=lit('{"v":1e16}')),
    dict(id="sample_token_neg_9007199254740993", category="proposal_sample_tokens",
         description="负的安全域外整数", input=lit('{"v":-9007199254740993}')),
    dict(id="sample_token_30_digit_int", category="proposal_sample_tokens",
         description="30 位十进制整数（既有编码器测试用例）", input=lit('{"v":123456789012345678901234567890}')),
    dict(id="sample_token_zero", category="proposal_sample_tokens",
         description="普通零", input=lit('{"v":0}')),

    # --- non-finite / constant rejects ---
    dict(id="reject_1e309", category="number_nonfinite_reject",
         description="float(token)=inf：拒绝", input=lit('{"v":1e309}'), reject="device_ai_number_nonfinite"),
    dict(id="reject_neg_1e400", category="number_nonfinite_reject",
         description="负向溢出：拒绝", input=lit('{"v":-1e400}'), reject="device_ai_number_nonfinite"),
    dict(id="reject_nan_constant", category="number_nonfinite_reject",
         description="NaN 常量：parse_constant 钩子拒绝", input=lit('{"v":NaN}'), reject="device_ai_number_invalid"),
    dict(id="reject_infinity_constant", category="number_nonfinite_reject",
         description="Infinity 常量：拒绝", input=lit('{"v":Infinity}'), reject="device_ai_number_invalid"),
    dict(id="reject_neg_infinity_constant", category="number_nonfinite_reject",
         description="-Infinity 常量：拒绝", input=lit('{"v":-Infinity}'), reject="device_ai_number_invalid"),

    # --- big integers: no digit-length bound in the parser ---
    dict(id="big_integer_310_digits", category="big_integer",
         description=">309 位十进制整数合法（B02）：parser 无位数上限", input=lit('{"v":' + "9" * 310 + '}')),
    dict(id="big_integer_2001_digits", category="big_integer",
         description=">2000 位整数合法：实际上限只有 MAX_NODES 与包字节，不存在长度界", input=lit('{"v":' + "9" * 2001 + '}')),

    # --- scientific notation variants: case and sign preserved verbatim ---
    dict(id="sci_1E_plus_5", category="scientific_notation",
         description="大写 E 与显式正号保留", input=lit('{"v":1E+5}')),
    dict(id="sci_1e5", category="scientific_notation",
         description="无符号指数保留", input=lit('{"v":1e5}')),
    dict(id="sci_neg_1_5E_minus_3", category="scientific_notation",
         description="大写 E 负指数：拼写逐字符保留", input=lit('{"v":-1.5E-3}')),
    dict(id="sci_5e_minus_324_subnormal", category="scientific_notation",
         description="最小次正规数：有限，接受", input=lit('{"v":5e-324}')),
    dict(id="sci_1e_plus_02", category="scientific_notation",
         description="带前导零指数保留", input=lit('{"v":1e+02}')),
    dict(id="sci_float_1_0", category="scientific_notation",
         description="整数部分+小数点形式保留", input=lit('{"v":1.0}')),
    dict(id="sci_float_neg_0_0", category="scientific_notation",
         description="浮点负零：与整数 -0、0 同值不同 sha", input=lit('{"v":-0.0}')),

    # --- lexeme spelling counterparts (same binary64 value, different sha) ---
    dict(id="spelling_1_23", category="lexeme_spelling_counterpart",
         description="与 sample_token_1_2300 数值相同、canonical 不同", input=lit('{"v":1.23}')),
    dict(id="spelling_zero", category="lexeme_spelling_counterpart",
         description="与 -0 数值相同、canonical 不同；sci_float_neg_0_0 是第三种拼写", input=lit('{"v":0}')),

    # --- string escapes ---
    dict(id="escape_non_bmp_raw", category="string_escape",
         description="原字符 𝄞 U+1D11E 直接进入源文本", input=lit('{"k":"\U0001D11E"}')),
    dict(id="escape_non_bmp_surrogate_pair", category="string_escape",
         description="代理对转义输入：canonical 与原字符输入完全一致（规范化为原始 UTF-8）",
         input=lit('{"k":"\\ud834\\udd1e"}')),
    dict(id="escape_nul", category="string_escape",
         description="\\u0000：字符串内 NUL 合法，canonical 以 \\u0000 转义输出", input=lit('{"x":"\\u0000"}')),
    dict(id="escape_control_shortcuts", category="string_escape",
         description="\\u0001 与 \\t \\n：控制字符转义集（<0x20）", input=lit('{"x":"a\\u0001b\\tc\\nd"}')),
    dict(id="escape_quote_backslash_solidus", category="string_escape",
         description="引号/反斜杠转义保留；\\/ 规范化为未转义的 /", input=lit('{"q":"\\"","b":"\\\\","s":"\\/"}')),
    dict(id="escape_raw_0x7f", category="string_escape",
         description="原始 DEL 0x7F：JSON 允许，canonical 不转义", input=lit('{"x":"\x7f"}')),
    dict(id="escape_raw_u2028", category="string_escape",
         description="原始 U+2028 行分隔符：canonical 不转义（跨 Host 陷阱点）", input=lit('{"x":"\u2028"}')),
    dict(id="escape_chinese_keys_and_text", category="string_escape",
         description="中文键值原样 UTF-8 输出；键重排（品<文）", input=lit('{"文本":"中文/ABC","品牌":"米其林"}')),
    dict(id="escape_emoji_key", category="string_escape",
         description="emoji 键 😀 U+1F600 原样输出", input=lit('{"\U0001F600":"smile"}')),

    # --- codepoint key ordering ---
    dict(id="sort_trap_ff21_vs_10000", category="key_sort_codepoint",
         description="codepoint 序：U+FF21 < U+10000；UTF-16 码元序相反（TS/Java 默认排序会排错）",
         input=lit('{"\U00010000":1,"\uff21":2}')),
    dict(id="sort_private_use_e000_vs_10000", category="key_sort_codepoint",
         description="U+E000 < U+10000（codepoint 序），同 UTF-16 陷阱", input=lit('{"\U00010000":1,"\ue000":2}')),
    dict(id="sort_nested_multilevel_arrays_ordered", category="key_sort_codepoint",
         description="多级嵌套逐层重排；数组保源序 [3,1,2] 不排序", input=lit('{"z":1,"a":2,"中":3,"A":4,"0":5,"!":6,"nested":{"y":[3,1,2],"x":null}}')),

    # --- depth boundary (AST depth, root = 0, MAX_DEPTH = 32) ---
    dict(id="depth_32_arrays_accept", category="depth_bound",
         description="32 层嵌套数组（叶在 AST 深度 32）：过", input=lit("[" * MAX_DEPTH + "0" + "]" * MAX_DEPTH)),
    dict(id="depth_33_arrays_reject", category="depth_bound",
         description="33 层：拒（文本预扫描界 MAX_DEPTH+1=33 放行，AST 检查拒绝）",
         input=lit("[" * (MAX_DEPTH + 1) + "0" + "]" * (MAX_DEPTH + 1)), reject="device_ai_json_depth"),
    dict(id="depth_32_ast_with_empty_tail_containers", category="depth_bound",
         description="文本 33 层但最内层为空容器（AST 深度 32 的空 list）：过——空容器不产生更深子节点",
         input=lit("[" * 31 + "[[]]" + "]" * 31)),

    # --- node-count boundary (every AST node counts; keys are not nodes) ---
    dict(id="node_bound_accept_250000", category="node_bound", sha_only=True,
         description="数组1 + 249999 个数字 = MAX_NODES=250000 节点：过（模板输入，sha 绑定）",
         input=tpl("[", "0,", 249998, "0]")),
    dict(id="node_bound_reject_250001", category="node_bound",
         description="250001 节点：拒（模板输入）", input=tpl("[", "0,", 249999, "0]"),
         reject="device_ai_json_nodes"),

    # --- syntax / structure rejects (real parser behavior) ---
    dict(id="reject_duplicate_key", category="syntax_reject",
         description="重复键", input=lit('{"a":1,"a":2}'), reject="device_ai_json_duplicate_key"),
    dict(id="reject_duplicate_key_escaped", category="syntax_reject",
         description="反转义后碰撞：\\u0061 == a", input=lit('{"a":1,"\\u0061":2}'), reject="device_ai_json_duplicate_key"),
    dict(id="reject_duplicate_key_escaped_surrogate_vs_raw", category="syntax_reject",
         description="代理对转义键与原 emoji 键反转义后碰撞", input=lit('{"\U0001F600":1,"\\ud83d\\ude00":2}'),
         reject="device_ai_json_duplicate_key"),
    dict(id="reject_bom_prefix", category="syntax_reject",
         description="UTF-8 BOM 开头", input=lit("\ufeff{}"), reject="device_ai_json_bom"),
    dict(id="reject_trailing_comma_array", category="syntax_reject",
         description="数组尾随逗号", input=lit("[1,]"), reject="device_ai_json_invalid"),
    dict(id="reject_trailing_comma_object", category="syntax_reject",
         description="对象尾随逗号", input=lit('{"a":1,}'), reject="device_ai_json_invalid"),
    dict(id="reject_single_quotes", category="syntax_reject",
         description="单引号字符串", input=lit("{'a':1}"), reject="device_ai_json_invalid"),
    dict(id="reject_raw_newline_in_string", category="syntax_reject",
         description="字符串内裸写控制字符（LF）", input=lit('{"x":"a\nb"}'), reject="device_ai_json_invalid"),
    dict(id="reject_leading_zero_number", category="syntax_reject",
         description="前导零 01", input=lit('{"x":01}'), reject="device_ai_json_invalid"),
    dict(id="reject_trailing_value", category="syntax_reject",
         description="顶层多值", input=lit("{} {}"), reject="device_ai_json_invalid"),
    dict(id="reject_unclosed_object", category="syntax_reject",
         description="未闭合对象", input=lit('{"a":1'), reject="device_ai_json_invalid"),
    dict(id="reject_empty_input", category="syntax_reject",
         description="空输入：容量拒绝（非语法）", input=lit(""), reject="device_ai_package_capacity"),
    dict(id="reject_invalid_utf8", category="syntax_reject",
         description="无效 UTF-8 字节 0xFF（bytes 输入形态）", input=byt("7b2278223a22ff227d"),
         reject="device_ai_json_utf8"),
    dict(id="reject_unpaired_surrogate_escape", category="syntax_reject",
         description="孤立代理项 \\ud800：loads 成功但 UTF-8 严格编码失败", input=lit('{"x":"\\ud800"}'),
         reject="device_ai_json_unicode"),

    # --- scalars, booleans, null, empty containers, mixed nesting (top level accepted) ---
    dict(id="scalar_top_number_42", category="scalar_and_container",
         description="顶层标量被接受：parser 是 strict JSON value parser（真实行为）", input=lit("42")),
    dict(id="scalar_top_text", category="scalar_and_container",
         description="顶层字符串", input=lit('"text"')),
    dict(id="scalar_top_true", category="scalar_and_container",
         description="顶层布尔", input=lit("true")),
    dict(id="scalar_top_null", category="scalar_and_container",
         description="顶层 null", input=lit("null")),
    dict(id="top_empty_object", category="scalar_and_container",
         description="空对象", input=lit("{}")),
    dict(id="top_empty_array", category="scalar_and_container",
         description="空数组", input=lit("[]")),
    dict(id="mixed_nested_bools_null_empty", category="scalar_and_container",
         description="布尔/null/空字符串/空容器/控制字符混合嵌套（键重排 a<b<z）",
         input=lit('{"b":[true,false,null,"","中文/\\u0001"],"a":{},"z":[[]]}')),

    # --- encode disambiguation both directions (draft-b Top1 / E2 lock) ---
    dict(id="disambig_number_5", category="encode_disambiguation",
         description="源 5 → DeviceAIValue number 分支（携带 token DTO）", input=lit("5")),
    dict(id="disambig_lookalike_token_dto", category="encode_disambiguation",
         description="源对象形似 token DTO → structured 分支（text 叶子）；与源 5 编码结果不同",
         input=lit('{"schema":"device-number-token@1","token":"5"}')),
    dict(id="disambig_nested_number", category="encode_disambiguation",
         description="嵌套位置的真数字（数组项/对象值）", input=lit('{"a":[5,true,{"token":5}]}')),
    dict(id="disambig_nested_lookalike", category="encode_disambiguation",
         description="嵌套位置的形似 token DTO 对象", input=lit('{"a":[{"schema":"device-number-token@1","token":"5"},true,{"token":{"schema":"device-number-token@1","token":"5"}}]}')),
]

CROSS_INVARIANTS = {
    "sha256_must_differ": [
        ["sample_token_1_2300", "spelling_1_23"],
        ["sample_token_neg_zero_integer", "spelling_zero"],
        ["sample_token_neg_zero_integer", "sci_float_neg_0_0"],
        ["spelling_zero", "sci_float_neg_0_0"],
    ],
    "canonical_must_match": [
        ["escape_non_bmp_raw", "escape_non_bmp_surrogate_pair"],
    ],
    "encoded_must_differ": [
        ["disambig_number_5", "disambig_lookalike_token_dto"],
        ["disambig_nested_number", "disambig_nested_lookalike"],
    ],
}

BEHAVIORAL_NOTES = [
    "顶层标量（数字/字符串/true/false/null）被接受：parse_exact_json 是 strict JSON value parser，"
    "不要求顶层为 object/array。encoder-spec.md 未对此明示，此处按真实行为冻结。",
    "整数 token 无位数上限（310 位、2001 位均合法）；实际上限来自 MAX_NODES=250000 与 MAX_PACKAGE_BYTES=8MiB。"
    "浮点 token 仅要求 float(token) 在 binary64 下有限：1e-5000 下溢为 0.0 仍接受且保留 lexeme；"
    "1e309 → device_ai_number_nonfinite；NaN/Infinity/-Infinity 常量 → device_ai_number_invalid。",
    "canonical 字符串转义集（与 ECMAScript JSON.stringify 一致）：\\\" 与 \\\\、\\b \\f \\n \\r \\t 快捷转义、"
    "其余 <0x20 控制字符用 \\uXXXX（小写十六进制）；不转义 /、0x7F、U+2028/U+2029；"
    "非 ASCII（含非 BMP）原样 UTF-8 输出，绝不输出代理对转义。输入中的 \\ud834\\udd1e 与原字符 𝄞 规范化为同一 canonical。",
    "对象键按 codepoint 升序（=UTF-8 字节序；≠UTF-16 码元序：U+FF21 排在 U+10000 之前，"
    "而 UTF-16 序相反）。canonical_exact_json 与 DeviceAIValue structured.fields 用同一排序；数组保源序。",
    "重复键在反转义后判定：{\"a\":1,\"\\u0061\":2} 与 {\"😀\":1,\"\\ud83d\\ude00\":2} 均拒绝。",
    "深度按 AST 计（根=0），MAX_DEPTH=32：33 层嵌套拒；文本预扫描界 MAX_DEPTH+1=33 与 AST 界等价，"
    "空容器可位于 AST 最深层（depth_32_ast_with_empty_tail_containers）。",
    "节点预算：每个 AST 节点计 1（容器/标量/NumberLexeme），对象键名不计独立节点；"
    "number token 另受同值计数上限约束。250000 节点过、250001 拒。",
    "sha256 = sha256(canonical_exact_json(ast))，无前缀（与 DeviceProjection.sha256 同式）；"
    "sha256_namespaced = sha256(namespace_utf8 + b\"\\x00\" + canonical)，namespace 见 constants。"
    "encoded（DeviceAIValue）绝不参与哈希，也不可从哈希反推。",
    "编码歧义双向：源 5 与源 {\"schema\":\"device-number-token@1\",\"token\":\"5\"} 的 encoded 必须不同"
    "（number vs structured 分支）。封存核心 token_dto() 对二者输出同形（歧义证据，见 encoder-spec.md 第 1 节），"
    "不得作为 DeviceAIValue 使用。",
    "所有拒绝均 fail-closed 且错误码为封闭集合；消息不含源内容。本文件只覆盖 Python 参考侧，"
    "TS/Rust/Java 对拍未运行，numeric_cross_host_literal_vectors 在三 Host 全绿前保持 false。",
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def finalize_input(inp: dict, raw: bytes) -> dict:
    if inp["form"] == "literal":
        return {"form": "literal", "text": inp["text"], "utf8_hex": raw.hex()}
    if inp["form"] == "bytes":
        return {"form": "bytes", "utf8_hex": raw.hex()}
    return dict(inp)


def main() -> None:
    ids = [definition["id"] for definition in VECTOR_DEFS]
    assert len(ids) == len(set(ids)), "duplicate vector ids"
    for relation in CROSS_INVARIANTS.values():
        for first, second in relation:
            assert first in ids and second in ids, (first, second)

    records = []
    for definition in VECTOR_DEFS:
        raw = expand(definition["input"])
        entry = {"id": definition["id"], "category": definition["category"],
                 "description": definition["description"],
                 "input": finalize_input(definition["input"], raw),
                 "input_byte_count": len(raw)}
        if "reject" in definition:
            try:
                encoder.encode_source_bytes(raw)
            except ProjectionError as error:
                assert error.code == definition["reject"], (definition["id"], error.code)
                entry["state"] = "rejected"
                entry["errors"] = [error.code]
            else:
                raise SystemExit(f"{definition['id']}: expected {definition['reject']}, got acceptance")
        else:
            ast = parse_exact_json(raw)
            canonical = canonical_exact_json(ast)
            encoded, digest = encoder.encode_source_bytes(raw)
            assert digest == sha(canonical), definition["id"]
            namespaced = encoder.encode_source_bytes(raw, namespace=NAMESPACE)[1]
            assert namespaced == exact_digest(ast, namespace=NAMESPACE), definition["id"]
            entry["state"] = "accepted"
            entry["sha256"] = digest
            entry["sha256_namespaced"] = namespaced
            if definition.get("sha_only"):
                entry["output_binding"] = "sha256_only_size"
                entry["canonical_byte_count"] = len(canonical)
                entry["omitted_fields"] = ["canonical", "encoded", "encoded_canonical_text"]
                entry["omission_reason"] = ("input/canonical are ~0.5MB; the template-expanded input plus "
                                            "sha256/sha256_namespaced bind the output completely")
            else:
                entry["canonical"] = {"text": canonical.decode("utf-8"), "utf8_hex": canonical.hex()}
                entry["encoded"] = encoded
                entry["encoded_canonical_text"] = json.dumps(
                    encoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        records.append(entry)

    by_category: dict[str, int] = {}
    for entry in records:
        by_category[entry["category"]] = by_category.get(entry["category"], 0) + 1
    payload = {
        "schema": SCHEMA,
        "state": "generated_and_self_checked",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": ("E1 跨 Host 数值/canonical/DeviceAIValue 编码基准向量（Python 参考实现侧权威预期输出）。"
                    "供 TS/Rust/Java 差分对拍与 tests/test_e1_vectors.py 重放锁定；"
                    "三 Host 全绿前 numeric_cross_host_literal_vectors 保持 false。"),
        "warning": ("Synthetic JSON grammar/lexeme vectors, not tire measurements or frozen domain facts. "
                    "Floating tokens retain source binary64 semantics, including finite underflow; "
                    "lexeme retention adds no precision. No TS/Rust/Java parity run has been executed against "
                    "this file yet; public wire stays unfrozen."),
        "sources": {
            "device_ai_projection.py": {"path": "apps/api/tire_api/device_ai_projection.py",
                                        "sha256": sha(PROJECTION_PATH.read_bytes())},
            "device_ai_value_encoder.py": {"path": "apps/api/tire_api/device_ai_value_encoder.py",
                                           "sha256": sha(ENCODER_PATH.read_bytes())},
        },
        "constants": {
            "MAX_DEPTH": MAX_DEPTH,
            "MAX_NODES": MAX_NODES,
            "MAX_PACKAGE_BYTES": MAX_PACKAGE_BYTES,
            "number_token_schema": "device-number-token@1",
            "namespaced_sha256_namespace": NAMESPACE,
        },
        "reference_runtime": {"python": sys.version},
        "replay_instructions": (
            "Expand each vector's input to bytes (literal: text.encode('utf-8'); bytes: "
            "bytes.fromhex(utf8_hex); template: (prefix + repeat*count + suffix).encode('utf-8')). "
            "Accepted vectors: run the host's lossless parser + canonical serializer + DeviceAIValue encoder and "
            "compare canonical bytes (text and utf8_hex), sha256, sha256_namespaced and encoded_canonical_text "
            "byte-for-byte; vectors with output_binding='sha256_only_size' bind via sha256/sha256_namespaced over "
            "the expanded input (canonical omitted for size). Rejected vectors must fail closed with the listed "
            "error codes. Cross-vector invariants must hold after replay."),
        "behavioral_notes": BEHAVIORAL_NOTES,
        "cross_vector_invariants": CROSS_INVARIANTS,
        "counts": {
            "total": len(records),
            "accepted": sum(entry["state"] == "accepted" for entry in records),
            "rejected": sum(entry["state"] == "rejected" for entry in records),
            "by_category": by_category,
        },
        "vectors": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"state": payload["state"], "output": str(OUTPUT),
                      "file_sha256": sha(OUTPUT.read_bytes()),
                      "counts": payload["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
