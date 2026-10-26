"""Explicit offline replay of one sealed S2 PDF through the unmodified pure parser.

Run from the repository root, passing a reviewed parser source and its SHA.
The historical PDF/matrix paths below are fixed; no search, download, application,
database, subprocess or replacement input is permitted. Output is a new private
artifact directory. A draft result is never formal integration or online proof.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sys


PDF_RELATIVE = ".artifacts/r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f/xiaomi-first-generation-2.pdf"
MATRIX_RELATIVE = ".artifacts/r81-su7-visual-review-7ce747a644e64296b051f815a0d7fe39/VISUAL_MATRIX.json"
PDF_SHA = "0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f"
PDF_SIZE = 3240150
MATRIX_SHA = "947f339855fcb2c1c9b0e238ecb06bcb830cc32b7012365918f40df3a355740a"
VEHICLE_ID = "xiaomi-su7-first-generation"
METHOD = "sha256_bound_reviewed_mapping"
MAPPING = "xiaomi-su7-first-generation-pdf@1"
SOURCE_URL = ("https://s1.xiaomiev.com/activity-outer-assets/0328/env/"
              "SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_source(raw):
    """Reject extra imports and I/O surfaces before executing reviewed source."""
    tree = ast.parse(raw)
    allowed = {"__future__", "hashlib", "json"}
    forbidden = {"open", "eval", "exec", "compile", "__import__", "getattr", "setattr", "globals", "locals"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden
        elif isinstance(node, ast.Attribute):
            assert not node.attr.startswith("__") or node.attr == "__init__"
    return tree


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser-source", type=Path, required=True)
    parser.add_argument("--parser-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--stage", choices=("draft", "integrated"), required=True)
    options = parser.parse_args(argv)
    repo = Path.cwd().resolve(strict=True)
    assert (repo / "apps/api/tire_api/adapters/xiaomi.py").is_file()
    source = options.parser_source.resolve(strict=True)
    output = options.output_root.resolve()
    assert source.name == "xiaomi_first_generation_pdf.py"
    if options.stage == "draft":
        assert source.is_relative_to(repo / ".artifacts") and source.parent.name == "drafts"
    else:
        assert source == repo / "apps/api/tire_api/adapters/xiaomi_first_generation_pdf.py"
    assert output.is_relative_to(repo / ".artifacts") and output != repo / ".artifacts" and not output.exists()
    assert re.fullmatch("[0-9a-f]{64}", options.parser_sha256)
    pdf_path, matrix_path = repo / PDF_RELATIVE, repo / MATRIX_RELATIVE
    # Only these three inputs and this probe source may be read after bootstrap.
    allowed_reads = {source, pdf_path.resolve(strict=True), matrix_path.resolve(strict=True), Path(__file__).resolve()}
    output.mkdir(parents=False, exist_ok=False)
    sys.dont_write_bytecode = True
    blocked = {"count": 0}

    def audit(event, args):
        if event.startswith(("socket.", "subprocess.", "sqlite3.")) or event in {"os.system", "os.spawn", "os.exec"}:
            blocked["count"] += 1
            raise PermissionError("pure_probe_forbidden_operation")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1], args[2]
            writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
            writing = writing or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if (writing and not path.is_relative_to(output)) or (not writing and path not in allowed_reads):
                blocked["count"] += 1
                raise PermissionError("pure_probe_path_not_allowed")

    sys.addaudithook(audit)
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)
        assert checks[name], name

    result = {"schema": "reviewed-vehicle-pdf-offline@1", "stage": options.stage, "checks": checks,
              "error_type": None, "online_capture": False, "database_used": False,
              "human_golden": False, "parser_bundle_execution": False, "readiness_changed": False}
    try:
        source_raw, matrix_raw = source.read_bytes(), matrix_path.read_bytes()
        check("parser_source_bound", sha(source_raw) == options.parser_sha256)
        check("review_matrix_bound", sha(matrix_raw) == MATRIX_SHA)
        safe_source(source_raw)
        check("parser_ast_stdlib_only", True)
        raw = pdf_path.read_bytes()
        check("original_s2_size_and_sha", len(raw) == PDF_SIZE and sha(raw) == PDF_SHA)
        try:
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            non_utf8 = True
        else:
            non_utf8 = False
        check("actual_input_is_non_utf8", non_utf8)
        module = {"__name__": "reviewed_pdf_probe_source"}
        exec(compile(source_raw, str(source), "exec"), module)
        parse = module["parse_reviewed_pdf"]
        error = module["ReviewedPDFError"]
        document = parse(raw, VEHICLE_ID)  # Actual public function; no monkeypatch or mock.
        matrix = json.loads(matrix_raw)
        check("closed_payload_shape", set(document) == {"vehicle", "trims", "fitments", "footnotes", "documents", "coverage", "parse_method", "mapping_id"})
        check("method_mapping_declarations", document["parse_method"] == METHOD and document["mapping_id"] == MAPPING and "parse_provenance" not in document)
        vehicle = document["vehicle"]
        check("vehicle_identity_and_unknown_year", vehicle == {"id": VEHICLE_ID, "manufacturer": {"id": "xiaomi", "name": "小米汽车"},
            "model": "SU7", "generation": "首代", "model_year": None, "region": "CN",
            "source_vehicle_id": "su7-first-generation", "source_version": "pdf-sha256:" + PDF_SHA})
        selectors = ("su7", "su7-pro", "su7-max")
        names = ("SU7", "SU7 Pro", "SU7 Max")
        check("three_printed_trim_columns", len(document["trims"]) == 3 and tuple(t["name"] for t in document["trims"]) == names)
        check("all_fifteen_cells_retained", len(document["fitments"]) == 15 and len({f["id"] for f in document["fitments"]}) == 15)
        symbol_map = {"●": "standard", "○": "optional", "-": "unavailable"}
        for selector, name, trim in zip(selectors, names, document["trims"]):
            check("trim_identity_" + selector, trim["id"] == VEHICLE_ID + "-" + selector and trim["source_trim_id"] == selector and trim["model_year"] is None)
            fits = [f for f in document["fitments"] if f["trim_id"] == trim["id"]]
            check("ordered_five_options_" + selector, len(fits) == 5 and trim["wheel_option_ids"] == [f["id"] for f in fits])
            for row, fit in zip(matrix["rows"], fits):
                tag = selector + "_" + row["id"]
                identity = {"vehicle_id": VEHICLE_ID, "trim_id": trim["id"], "reviewed_row_id": row["id"]}
                expected_id = sha(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())[:24]
                check("stable_id_" + tag, fit["id"] == expected_id)
                check("row_identity_" + tag, fit["trim_name"] == name and fit["wheel_option_name"] == row["label"] and fit["source_description"] == "\n".join(row["raw_tire_description_lines"]))
                front, rear = row["front"].replace(" ", ""), row["rear"].replace(" ", "")
                check("axles_and_availability_" + tag, fit["front"]["size"] == front and fit["rear"]["size"] == rear
                    and fit["staggered"] == (front != rear) and fit["wheel_diameter_inches"] == int(front.rsplit("R", 1)[1])
                    and fit["availability"] == symbol_map[row["availability"][name]["symbol"]])
                for axle in (fit["front"], fit["rear"]):
                    check("unknown_identity_" + tag + ("_front" if axle is fit["front"] else "_rear"), set(axle) == {"size", "load_index", "speed_rating", "oe_mark", "manufacturer_product_code", "matched_tire_variant_id"} and all(value is None for key, value in axle.items() if key != "size"))
                check("printed_family_" + tag, fit["source_tire_description"] == row["brand_as_printed"] + " " + row["family_as_printed"] + " 轮胎")
                reviewed = next(locator for locator in row["locators"] if locator["source"] == "S2")
                box = reviewed["subregions"][name.replace(" ", "_") + "_cell"]
                locator = "pdf-sha256:" + PDF_SHA + "#page=3&row=" + row["id"] + "&trim=" + selector + "&bbox=" + ",".join(map(str, box)) + "&canvas=1272,1800"
                check("locator_" + tag, fit["evidence_locator"] == locator)
                expected_constraints = ["前Brembo四活塞固定卡钳 + 打孔通风盘"] if row["id"] == "W3" else []
                if row["id"] == "W1" and selector == "su7-max":
                    expected_constraints = ["免费选装"]
                check("conditions_" + tag, fit["constraints"] == expected_constraints)
        check("three_exact_cltc_footnotes", document["footnotes"] == [f["trim"] + "：" + f["raw_semantic_transcription"] for f in matrix["footnotes"]])
        check("source_link_only", len(document["documents"]) == 1 and document["documents"][0]["url"] == SOURCE_URL and document["documents"][0]["status"] == "official_source_link")
        check("coverage_limits", all(document["coverage"][name] is True for name in ("axle_sizes", "wheel_options", "trim_mapping")) and all(document["coverage"][name] is False for name in ("model_year", "exact_tire_sku", "oe_mark")))
        baseline = json.dumps(document, ensure_ascii=False, sort_keys=True)
        document["fitments"][0]["front"]["size"] = "synthetic-caller-mutation"
        document["trims"][0]["wheel_option_ids"].clear()
        document["footnotes"].clear()
        fresh = parse(raw, VEHICLE_ID)
        check("returns_independent_fresh_objects", json.dumps(fresh, ensure_ascii=False, sort_keys=True) == baseline)
        for position, label in ((0, "signature"), (len(raw) // 2, "middle"), (len(raw) - 1, "last")):
            damaged = bytearray(raw); damaged[position] ^= 1
            try:
                parse(bytes(damaged), VEHICLE_ID)
            except error as exc:
                expected_code = "vehicle_pdf_invalid" if label == "signature" else "vehicle_pdf_revision_unreviewed"
                rejected = exc.code == expected_code
            else:
                rejected = False
            check("actual_single_byte_mutation_rejected_" + label, rejected)
        for value, vehicle_id, code, label in (
            ("text", VEHICLE_ID, "parser_input_invalid", "text"),
            (b"", VEHICLE_ID, "parser_input_invalid", "empty"),
            (b"not-pdf", VEHICLE_ID, "vehicle_pdf_invalid", "signature"),
            (b"%PDF-1.7", "xiaomi-su7-current", "vehicle_generation_not_verified", "generation"),
            (b"%PDF-" + b"x" * (8 * 1024 * 1024 - 4), VEHICLE_ID, "parser_input_too_large", "budget"),
            (b"%PDF-1.7\nsynthetic", VEHICLE_ID, "vehicle_pdf_revision_unreviewed", "unreviewed"),
            (b"%PDF-" + b"x" * (PDF_SIZE - 5), VEHICLE_ID, "vehicle_pdf_revision_unreviewed", "same_size_unknown_hash"),
        ):
            try:
                parse(value, vehicle_id)
            except error as exc:
                rejected = exc.code == code
            else:
                rejected = False
            check("synthetic_rejection_" + label, rejected)
        check("inputs_unchanged", sha(source.read_bytes()) == options.parser_sha256 and sha(matrix_path.read_bytes()) == MATRIX_SHA and sha(pdf_path.read_bytes()) == PDF_SHA)
        check("application_not_imported", "tire_api.main" not in sys.modules and "tire_api.db" not in sys.modules)
        check("no_forbidden_operation", blocked["count"] == 0)
        (output / "parsed.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
        result.update(parser_sha256=options.parser_sha256, matrix_sha256=MATRIX_SHA, pdf_sha256=PDF_SHA,
                      pdf_byte_count=PDF_SIZE, checks_passed=len(checks), success=True)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__, success=False)
    (output / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": result.get("success", False), "stage": options.stage,
                      "checks_passed": sum(checks.values()), "checks_total": len(checks), "error_type": result["error_type"],
                      "output": output.relative_to(repo).as_posix()}))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
