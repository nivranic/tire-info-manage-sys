"""SHA-256-bound reviewed mapping of one historical first-generation SU7 PDF.

Contract: docs/plans/2026-10-19-official-vehicle-pdf-contract.md, sections 1-3.
This pure function checks bytes and vehicle identity only. The caller must still
validate trusted source/URL/MIME/rights and persist a receipt before parsing.
It neither fetches nor opens files, imports the app, or enables online readiness.
The mapping is an agent-reviewed page-3 transcription, not OCR or a human Golden.
"""
from __future__ import annotations

import hashlib
import json


SOURCE_ID = "xiaomi-cn-vehicles"
FIRST_GENERATION_ID = "xiaomi-su7-first-generation"
SOURCE_URL = (
    "https://s1.xiaomiev.com/activity-outer-assets/0328/env/"
    "SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf"
)
CONTENT_TYPE = "application/pdf"
BODY_ENCODING = "binary"
MAX_INPUT_BYTES = 8 * 1024 * 1024
REVIEWED_BYTE_COUNT = 3240150
REVIEWED_RAW_SHA256 = "0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f"
PARSE_METHOD = "sha256_bound_reviewed_mapping"
MAPPING_ID = "xiaomi-su7-first-generation-pdf@1"

# Review provenance is source data, not a runtime path to load. All coordinates
# refer to the bound S2 page render, top-left origin, row/cell regions, not glyphs.
REVIEW_SOURCE = ".artifacts/r81-su7-visual-review-7ce747a644e64296b051f815a0d7fe39/VISUAL_MATRIX.json"
REVIEW_MATRIX_SHA256 = "947f339855fcb2c1c9b0e238ecb06bcb830cc32b7012365918f40df3a355740a"
REVIEW_PAGE_IMAGE_SHA256 = "e1c460e35440bb2cef1bdfb4269659971cfbc64821b4b58f915264235967c36c"
PDF_PAGE_ONE_BASED = 3
PRINTED_PAGE_NUMBER = "3"
RENDER_CANVAS = (1272, 1800)
DESCRIPTION_COLUMN = (86, 293)
ROW_REGION_X = (86, 1186)

# Local selectors represent the printed columns, not official numerical IDs.
_TRIMS = (
    ("su7", "SU7", 293, 590),
    ("su7-pro", "SU7 Pro", 590, 887),
    ("su7-max", "SU7 Max", 887, 1186),
)
# row, printed label, rim, front, rear, family text, original grey lines,
# package conditions, ordered availability, row y bounds.
_ROWS = (
    ("W1", "19英寸低风阻轮毂", 19, "245/45R19", "245/45R19", "米其林 e·Primacy 轮胎",
     ("前后 245/45 R19", "米其林 e·Primacy 轮胎"), (),
     ("standard", "standard", "optional"), 715, 835),
    ("W2", "19英寸运动轮毂", 19, "245/45R19", "245/45R19", "普利司通 TURANZA 6 轮胎",
     ("前后 245/45 R19", "普利司通 TURANZA 6", "轮胎"), (),
     ("unavailable", "unavailable", "standard"), 835, 975),
    ("W3", "20英寸运动轮毂 + 前Brembo四活塞固定卡钳 + 打孔通风盘", 20,
     "245/40R20", "245/40R20", "米其林 Pilot Sport EV 轮胎",
     ("前后 245/40 R20", "米其林 Pilot Sport EV", "轮胎"),
     ("前Brembo四活塞固定卡钳 + 打孔通风盘",),
     ("optional", "optional", "unavailable"), 975, 1161),
    ("W4", "20英寸运动轮毂", 20, "245/40R20", "265/40R20", "米其林 Pilot Sport EV 轮胎",
     ("前 245/40 R20", "后 265/40 R20", "米其林 Pilot Sport EV", "轮胎"), (),
     ("unavailable", "unavailable", "optional"), 1161, 1322),
    ("W5", "21英寸运动轮毂", 21, "245/35R21", "265/35R21", "倍耐力 P ZERO 轮胎",
     ("前 245/35 R21", "后 265/35 R21", "倍耐力 P ZERO 轮胎"), (),
     ("unavailable", "unavailable", "optional"), 1322, 1463),
)
_FOOTNOTES = (
    "SU7：米其林e·Primacy、米其林Pilot Sport EV轮胎CLTC续航里程分别为700km、628km",
    "SU7 Pro：米其林e·Primacy、米其林Pilot Sport EV轮胎CLTC续航里程分别为830km、758km",
    "SU7 Max：普利司通TURANZA 6、米其林e·Primacy、米其林Pilot Sport EV、倍耐力P ZERO轮胎CLTC续航里程分别为800km、810km、750km、725km",
)
FOOTNOTE_REGIONS = ((110, 1487, 1120, 1504), (110, 1504, 1120, 1521), (110, 1521, 1120, 1540))


class ReviewedPDFError(ValueError):
    """Fixed input failure codes only; never include received bytes or paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _option_id(vehicle_id: str, trim_id: str, row_id: str) -> str:
    # Exact stable_json/digest contract from tire_api/domain.py:27-32, kept
    # stdlib-only so this module remains safe to load in a sealed Parser bundle.
    value = {"vehicle_id": vehicle_id, "trim_id": trim_id, "reviewed_row_id": row_id}
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _axle(size: str) -> dict:
    return {"size": size, "load_index": None, "speed_rating": None, "oe_mark": None,
            "manufacturer_product_code": None, "matched_tire_variant_id": None}


def parse_reviewed_pdf(raw: bytes, vehicle_id: str) -> dict:
    """Instantiate the frozen mapping only for the reviewed original bytes.

    parse_method/mapping_id are declarations, not server parse_provenance. The
    future writer must bind the selected bundle and actual execution receipt;
    this function must not manufacture that six-key server-only identity block.
    """
    if type(vehicle_id) is not str or vehicle_id != FIRST_GENERATION_ID:
        raise ReviewedPDFError("vehicle_generation_not_verified")
    if type(raw) is not bytes or not raw:
        raise ReviewedPDFError("parser_input_invalid")
    if len(raw) > MAX_INPUT_BYTES:
        raise ReviewedPDFError("parser_input_too_large")
    if not raw.startswith(b"%PDF-"):
        raise ReviewedPDFError("vehicle_pdf_invalid")
    if len(raw) != REVIEWED_BYTE_COUNT or hashlib.sha256(raw).hexdigest() != REVIEWED_RAW_SHA256:
        raise ReviewedPDFError("vehicle_pdf_revision_unreviewed")

    trims, fitments = [], []
    for column, (selector, name, left, right) in enumerate(_TRIMS):
        trim_id = f"{vehicle_id}-{selector}"
        trim = {"id": trim_id, "name": name, "source_trim_id": selector,
                "model_year": None, "wheel_option_ids": []}
        for row_id, label, rim, front, rear, family, lines, package, available, top, bottom in _ROWS:
            option_id = _option_id(vehicle_id, trim_id, row_id)
            conditions = list(package)
            if row_id == "W1" and selector == "su7-max":
                conditions.append("免费选装")
            locator = (f"pdf-sha256:{REVIEWED_RAW_SHA256}#page=3&row={row_id}&trim={selector}"
                       f"&bbox={left},{top},{right},{bottom}&canvas=1272,1800")
            fitments.append({"id": option_id, "trim_id": trim_id, "trim_name": name,
                "wheel_option_name": label, "wheel_diameter_inches": rim,
                "availability": available[column], "front": _axle(front), "rear": _axle(rear),
                "staggered": front != rear, "source_tire_description": family,
                "constraints": conditions, "source_description": "\n".join(lines),
                "evidence_locator": locator})
            trim["wheel_option_ids"].append(option_id)
        trims.append(trim)

    return {
        "vehicle": {"id": vehicle_id, "manufacturer": {"id": "xiaomi", "name": "小米汽车"},
            "model": "SU7", "generation": "首代", "model_year": None, "region": "CN",
            "source_vehicle_id": "su7-first-generation", "source_version": f"pdf-sha256:{REVIEWED_RAW_SHA256}"},
        "trims": trims, "fitments": fitments, "footnotes": list(_FOOTNOTES),
        "documents": [{"url": SOURCE_URL, "title": "小米 SU7 参数配置表（首代历史版本）",
                       "status": "official_source_link"}],
        "coverage": {"axle_sizes": True, "wheel_options": True, "trim_mapping": True,
            "model_year": False, "exact_tire_sku": False, "oe_mark": False,
            "notice": "SHA-256 绑定的已复核历史 PDF 映射，仅对应该原件第3页；不是首代当前配置全集。"
                      "原表不证明具体轮胎 SKU、载重/速度或 OE 胎侧标记；CLTC为整车配置说明，不是轮胎性能评分。"},
        "parse_method": PARSE_METHOD, "mapping_id": MAPPING_ID,
    }
