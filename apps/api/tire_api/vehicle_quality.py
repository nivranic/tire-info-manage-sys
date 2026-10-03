"""Separate loss denominators for vehicle identity, trims and axle/wheel options."""
from .domain import stable_json
from .quality import assess_records, is_known, known_leaves


def record_key(row: dict) -> str | None:
    return stable_json({"id": row["id"]}) if is_known(row.get("id")) else None


def record_fields(row: dict) -> dict:
    # Stable keys/locators/duplicated display labels do not inflate field counts.
    ignored = {"id", "trim_id", "trim_name", "source_trim_id", "source_vehicle_id", "source_version",
               "wheel_option_ids", "evidence_locator", "source_description"}
    return {path: value for key, value in row.items() if key not in ignored
            for path, value in known_leaves(value, key).items()}


def assess_vehicle_quality(baseline: dict | None, candidate: dict) -> dict:
    groups = {}
    for name in ("vehicle", "trims", "fitments"):
        previous = ([baseline[name]] if name == "vehicle" else baseline[name]) if baseline else []
        current = [candidate[name]] if name == "vehicle" else candidate[name]
        groups[name] = assess_records(previous, current, record_key, record_fields, "vehicle-field-loss@1")
    report = {"ruleset": "vehicle-field-loss@1", "threshold": 0.3, "groups": groups,
              "reason_codes": sorted({reason for group in groups.values() for reason in group["reason_codes"]})}
    for key in ("baseline_rows", "candidate_rows", "aligned_rows", "lost_rows", "known_fields", "lost_field_count"):
        report[key] = sum(group[key] for group in groups.values())
    for key in ("lost_fields", "lost_row_keys", "ambiguous_keys"):
        report[key] = [item for group in groups.values() for item in group[key]]
    report["row_loss_ratio"] = report["lost_rows"] / report["baseline_rows"] if report["baseline_rows"] else 0.0
    report["field_loss_ratio"] = report["lost_field_count"] / report["known_fields"] if report["known_fields"] else 0.0
    if baseline:
        old, new = baseline["vehicle"], candidate["vehicle"]
        if (any(old.get(key) != new.get(key) for key in ("id", "generation", "region", "source_vehicle_id"))
                or old["manufacturer"]["id"] != new["manufacturer"]["id"]):
            report["reason_codes"].append("vehicle_identity_changed")
    return report
