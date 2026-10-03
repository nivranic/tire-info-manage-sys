"""Source-function reference for TireQuery versus advanced TireFilter size boundaries. No I/O services."""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from tire_api.domain import TireQuery
from tire_api.query_filters import TireFilter, _matches


def main() -> None:
    if unicodedata.unidata_version != "15.0.0":
        raise RuntimeError("Use the frozen Unicode 15.0.0 Python runtime")
    inputs = [
        ("205/55R20", "205/55R𝟚𝟘", {}),
        ("205/55R𝟚𝟘", "205/55R20", {}),
        ("205/55R20", "٢٠٥/٥٥R٢٠", {}),
        ("205/55R20", "٢٠٥/٥٥R20", {}),
        ("205/55ZR20", "205/55R20", {}),
        ("205/55R20", "205/55ZR20", {}),
        ("205/55R20", "205/55R20", {"source_field_conflicts": [{"field": "identity.size"}]}),
        (None, "205/55R20", {}),
        ("205/55R20", "205/55R20", {"utqg_treadwear": 200}),
    ]
    cases = []
    for row_size, draft, facts in inputs:
        row = {"model": "Fixture Tire", "size": row_size, "facts": facts}
        query = TireQuery(size=draft).canonical()
        advanced = TireFilter(field="size", op="eq", value=draft).model_dump(exclude_none=True)
        basic = _matches(row, {"field": "size", "op": "eq", "value": query["size"]})
        advanced_match = _matches(row, advanced)
        false_predicate = _matches(row, {"field": "model", "op": "eq", "value": "different model"})
        combined = False if false_predicate is False else basic
        cases.append({"row": row, "draft_query": {"size": draft}, "canonical_query": query,
                      "advanced_filter": advanced, "basic_match": basic,
                      "advanced_match": advanced_match, "basic_with_false_model": combined})
    value = {"schema": "tire-basic-query-reference@1", "unicode_version": unicodedata.unidata_version,
             "definition": "basic size condition expected=TireQuery canonical raw size; row=_matches/_read; advanced expected=TireFilter normalized value",
             "source_hashes": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                               for name in ["apps/api/tire_api/domain.py", "apps/api/tire_api/query_filters.py"]},
             "cases": cases, "source_calls": 0, "parser_calls": 0, "model_calls": 0, "database_calls": 0}
    destination = ROOT/".artifacts/query-fallback49/basic-query-reference-a.json"
    if destination.exists():
        raise RuntimeError("Refuse to overwrite reference evidence")
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
