"""Build/replay a private 023 baseline; run only through the reviewed gate driver.

This is a baseline generated from frozen current 023 source, containing synthetic
historical data. It is not a normal-database backup or a retained production DB.
Top-level imports deliberately use only the standard library so replay does not
load production models, migrations, or SQLAlchemy. This module never publishes
fixture files into the source tree.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import sys
from datetime import UTC, datetime, timedelta


FIXTURE_SCHEMA = "vehicle-binary-023-private-baseline@1"
PRODUCTS = ("schema_023.sql", "seed_023.sql", "expected_023.json", "source-index.json", "README.md")
VERSIONS = [
    "001_verification_validators", "002_monitor_rule_conditions", "003_parser_release_provenance",
    "004_query_selection_filters", "005_variant_identity_contract", "006_source_settings",
    "007_monitor_tasks", "008_recall_discovery_monitoring", "009_ai_streaming", "010_offline_packs",
    "011_query_fallback_policies", "012_device_ai_preparations", "013_device_ai_ledger_triggers",
    "014_local_sessions_user", "015_local_sessions_user_index", "016_private_interests",
    "017_interest_governance_catalog", "018_interest_manual_applicability", "019_test_sku_links",
    "020_source_materials", "021_candidate_ai_assistance", "022_webhook_delivery", "023_external_api_keys",
]
AT = datetime(2026, 1, 1, tzinfo=UTC)
SESSION = "synthetic-023-session"


def _require(condition, code):
    if not condition:
        raise RuntimeError(code)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _hash(_json(value).encode("utf-8"))


def _write(path, data):
    with Path(path).open("xb") as stream:
        stream.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def _relative(value):
    path = PurePosixPath(value)
    _require(isinstance(value, str) and not path.is_absolute() and ".." not in path.parts
             and "\\" not in value and ":" not in value and str(path) == value, "relative_path_invalid")
    return path


def _plain(path):
    path = Path(path).absolute()
    for item in [*reversed(path.parents), path]:
        if item.exists():
            info = item.lstat()
            _require(not item.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400,
                     "redirected_path_forbidden")
    return path


def _output(output_root, phase):
    root = _plain(output_root)
    _require(root.is_dir(), "output_root_missing")
    private = _plain(root / "private")
    _require(private.is_dir(), "private_root_missing")
    database = private / ("capture.sqlite" if phase == "capture" else "replay.sqlite")
    _require(not database.exists(), "database_already_exists")
    return root, private, database


def _verified_source(root, manifest):
    root = _plain(root)
    _require(isinstance(manifest, dict) and isinstance(manifest.get("files"), dict)
             and isinstance(manifest.get("environment"), dict), "source_manifest_invalid")
    for name, metadata in manifest["files"].items():
        relative = _relative(name)
        path = _plain(root.joinpath(*relative.parts))
        _require(path.is_file() and path.resolve().is_relative_to(root.resolve()), "source_file_invalid")
        data = path.read_bytes()
        _require(len(data) == metadata["bytes"] and _hash(data) == metadata["sha256"], "source_bytes_changed")
    actual = {p.relative_to(root).as_posix() for p in (root / "apps/api/tire_api").rglob("*.py")}
    declared = {p for p in manifest["files"] if p.startswith("apps/api/tire_api/") and p.endswith(".py")}
    _require(actual == declared and len(actual) == 140, "package_closure_changed")
    _require({"apps/api/pyproject.toml", "apps/api/uv.lock", "scripts/build_vehicle_binary_023_fixture.py"}
             <= manifest["files"].keys(), "source_closure_incomplete")
    return root


def _model_modules(root):
    modules, tables = [], set()
    for path in sorted((root / "apps/api/tire_api").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if (isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__"
                                                        for t in item.targets)
                        and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str)):
                    names.append(item.value.value)
        if names:
            modules.append(".".join(path.relative_to(root / "apps/api").with_suffix("").parts))
            for name in names:
                _require(name not in tables, "duplicate_model_table")
                tables.add(name)
    _require(len(modules) == 30 and len(tables) == 134, "model_table_inventory_changed")
    return modules, tables


def _check_imports(root, manifest):
    _require("tire_api.main" not in sys.modules, "main_import_forbidden")
    loaded = {}
    for name, module in sorted(sys.modules.items()):
        if name != "tire_api" and not name.startswith("tire_api."):
            continue
        path = getattr(module, "__file__", None)
        _require(path is not None, "unbound_package_import")
        path = _plain(path).resolve()
        _require(path.is_relative_to(root.resolve()), "live_source_import_forbidden")
        relative = path.relative_to(root.resolve()).as_posix()
        _require(relative in manifest["files"] and _hash(path.read_bytes()) == manifest["files"][relative]["sha256"],
                 "import_source_changed")
        loaded[name] = relative
    return loaded


def _insert(connection, base, table, **values):
    connection.execute(base.metadata.tables[table].insert().values(**values))


def _source_body(version, reduced=False):
    cells = [
        {"paramName": "19英寸合成测试轮毂", "paramValue": "●",
         "paramDesc": "前轮胎 245/45 R19\n后轮胎 245/45 R19\n合成轮胎说明；仅作回归证据"},
        {"paramName": "20英寸合成测试轮毂", "paramValue": "○",
         "paramDesc": "前轮胎 245/40 R20\n后轮胎 265/40 R20\n合成选装轮胎说明"},
    ]
    return _json({"code": 0, "data": {"paramComparisonTableVOList": [{
        "carItemId": 500023067, "brandCode": "xiaomi", "pdfFileName": "新一代SU7 合成测试参数表",
        "version": version, "carSsuDataList": [{"carSsuId": 900001, "pcCarVersionName": "SU7 合成测试版"}],
        "groups": [{"groupName": "轮毂/轮胎", "footnote": ["合成历史，不是官方真实车型规格"],
                    "paramComparisonCols": [{"carSsuId": 900001, "carItemId": 500023067,
                                             "paramComparisonCells": cells[:1] if reduced else cells}]}],
    }]}})


def _seed_core(database, base):
    # These are pure parsing/quality functions. No Parser worker, fetch, live API,
    # QueryService execution, release evaluation, or reparse execution is invoked.
    from tire_api.adapters import xiaomi
    from tire_api.vehicle_quality import assess_vehicle_quality
    from tire_api.vehicles import fitment_fact_hash, validate_vehicle_structure
    from tire_api.quarantine_review import binding

    bodies = {"L": _source_body("synthetic-legacy"), "A": _source_body("synthetic-A"),
              "B": _source_body("synthetic-B"), "Q": _source_body("synthetic-loss", True),
              "R": '{"code":0,"合成":"无法解析的历史观察"}'}
    payloads = {key: xiaomi.parse_config(body) for key, body in bodies.items() if key != "R"}
    for payload in payloads.values():
        validate_vehicle_structure(payload, payload["fitments"])
    quality = assess_vehicle_quality(payloads["B"], payloads["Q"])
    _require(bool(quality["reason_codes"]), "synthetic_loss_not_detected")
    _require(fitment_fact_hash(payloads["A"]) == fitment_fact_hash(payloads["B"]), "same_fact_case_invalid")
    query = {"vehicle_id": xiaomi.CURRENT_ID}
    query_key = _digest(query)
    hashes = {key: _hash(body.encode("utf-8")) for key, body in bodies.items()}
    fit = payloads["B"]["fitments"][0]
    trim = payloads["B"]["trims"][0]
    shared = {"source_id": xiaomi.SOURCE_ID, "source_url": xiaomi.API_URL,
              "content_type": "application/json", "parser_version": xiaomi.PARSER_VERSION, "parser_identity": None}
    assets = {}
    with database.engine.begin() as connection:
        add = lambda table, **values: _insert(connection, base, table, **values)
        add("local_sessions", id=SESSION, created_at=AT, expires_at=AT + timedelta(days=30), user_id=None)
        add("vehicle_manufacturers", id="xiaomi", name="小米汽车")
        add("vehicle_models", id=xiaomi.CURRENT_ID, manufacturer_id="xiaomi", name="SU7", generation="新一代",
            model_year=None, region="CN", source_vehicle_id="500023067")
        add("vehicle_trims", id=trim["id"], vehicle_id=xiaomi.CURRENT_ID, source_trim_id=trim["source_trim_id"],
            name=trim["name"], model_year=None)
        for number in range(7):
            add("query_runs", id=f"synthetic-q{number}", session_id=SESSION, source_id=xiaomi.SOURCE_ID,
                query_key=query_key, query=query, selection_filters=None, source_access_generation=None,
                fallback_policy="never", state="live" if number in (0, 1, 2, 3, 5) else "source_unavailable",
                reason="source_quality_quarantined" if number == 4 else "parser_failed" if number == 6 else None,
                created_at=AT + timedelta(minutes=number))
        for number, key in ((1, "A"), (2, "A"), (3, "B"), (4, "Q"), (5, "Q"), (6, "R")):
            raw = bodies[key].encode("utf-8")
            add("raw_captures", id=f"synthetic-c{number}", query_id=f"synthetic-q{number}", query_key=query_key,
                target_kind="vehicle", raw_hash=hashes[key], raw_body=raw, byte_count=len(raw),
                observed_at=AT + timedelta(minutes=number), **shared)
            if hashes[key] not in assets:
                add("evidence_objects", raw_hash=hashes[key], byte_count=len(raw), created_at=AT + timedelta(minutes=number))
                assets[hashes[key]] = raw
            add("capture_objects", capture_id=f"synthetic-c{number}", raw_hash=hashes[key])
        for label, key, number, version in (("legacy", "L", 0, 1), ("a", "A", 1, 1),
                                            ("b", "B", 3, 1), ("accepted-loss", "Q", 5, 2)):
            add("vehicle_snapshots", id=f"synthetic-vs-{label}", vehicle_id=xiaomi.CURRENT_ID,
                raw_hash=hashes[key], body=bodies[key], observed_at=AT + timedelta(minutes=number),
                payload=payloads[key], fact_hash=fitment_fact_hash(payloads[key]), fact_version=version, **shared)
            for index, specification in enumerate(payloads[key]["fitments"]):
                add("vehicle_wheel_fitments", id=f"synthetic-fit-{label}-{index}", option_id=specification["id"],
                    trim_id=trim["id"], snapshot_id=f"synthetic-vs-{label}", version=version, specification=specification)
        for number, label in ((0, "legacy"), (1, "a"), (2, "a"), (3, "b"), (5, "accepted-loss")):
            add("vehicle_verifications", id=f"synthetic-v{number}", snapshot_id=f"synthetic-vs-{label}",
                query_id=f"synthetic-q{number}", vehicle_id=xiaomi.CURRENT_ID, parser_identity=None,
                verified_at=AT + timedelta(minutes=number))
        add("vehicle_quarantines", id="synthetic-quarantine", query_id="synthetic-q4", vehicle_id=xiaomi.CURRENT_ID,
            previous_snapshot_id="synthetic-vs-b", raw_hash=hashes["Q"], body=bodies["Q"],
            observed_at=AT + timedelta(minutes=4), payload=payloads["Q"], quality=quality, **shared)
        binding_hash = binding("vehicle", xiaomi.SOURCE_ID, query_key, "synthetic-vs-b",
                               {"body": bodies["Q"], "url": xiaomi.API_URL, **shared}, payloads["Q"], quality)
        add("quarantine_reviews", id="synthetic-review", quarantine_id="synthetic-quarantine",
            binding_hash=binding_hash, revision=1, action="approve", operator="synthetic reviewer",
            reason="Synthetic historical approval for preservation regression only", actor_session_id=SESSION,
            created_at=AT + timedelta(minutes=4, seconds=10), expires_at=AT + timedelta(days=1))
        add("quarantine_approval_uses", review_id="synthetic-review", query_id="synthetic-q5",
            used_at=AT + timedelta(minutes=5))
        add("rejected_observations", id="synthetic-rejected", query_id="synthetic-q6", query_key=query_key,
            target_kind="vehicle", stage="parser", reason="parser_failed", raw_hash=hashes["R"],
            raw_body=bodies["R"].encode("utf-8"), observed_at=AT + timedelta(minutes=6), **shared)
        add("garage_vehicles", id="synthetic-garage", created_at=AT + timedelta(minutes=7))
        provenance = {"snapshot_id": "synthetic-vs-b", "source_id": xiaomi.SOURCE_ID, "source_url": xiaomi.API_URL,
                      "source_page": xiaomi.SOURCE_PAGE, "parser_version": xiaomi.PARSER_VERSION, "parser_identity": None,
                      "observed_at": "2026-01-01T00:03:00+00:00", "raw_hash": hashes["B"],
                      "evidence_path": "/v1/vehicle-evidence/synthetic-vs-b"}
        add("garage_revisions", id="synthetic-garage-r1", vehicle_id="synthetic-garage", revision=1,
            operation="create", archived=False, basis="copied_fitment", actor_session_id=SESSION,
            created_at=AT + timedelta(minutes=7),
            profile={"nickname": "合成车库", "manufacturer": "小米汽车", "model": "SU7", "model_year": None,
                     "generation": "新一代", "trim": trim["name"], "wheel_option": fit["wheel_option_name"],
                     "optional_wheels": [], "front": {"size": fit["front"]["size"], "current_variant_id": None},
                     "rear": {"size": fit["rear"]["size"], "current_variant_id": None}},
            fitment_reference={**provenance, "fitment_id": fit["id"], "availability": fit["availability"],
                               "constraints": fit["constraints"], "source_description": fit["source_description"]})
        add("audit_events", id="synthetic-audit", session_id=SESSION, query_id="synthetic-q3", consent_id=None,
            action="synthetic_preservation_sentinel", detail={"synthetic": True, "snapshot_id": "synthetic-vs-b"},
            created_at=AT + timedelta(minutes=8))
    for raw_hash, raw in assets.items():
        _require(database.object_store.put(raw) == raw_hash, "synthetic_object_hash_changed")
    return {"bodies": bodies, "payloads": payloads, "hashes": hashes, "query": query, "query_key": query_key,
            "quality": quality, "binding_hash": binding_hash, "provenance": provenance}


def _seed_pending(database, base, history):
    from tire_api.adapters import xiaomi
    from tire_api.parser_bundles import bundle_descriptor, seal_deployed_bundle, verify_bundle
    from tire_api.parser_releases import EvaluationCreate
    from tire_api.reparse import ReparseCreate
    manifest = seal_deployed_bundle()
    verify_bundle(manifest)
    descriptors = {source: bundle_descriptor(manifest, source) for source in manifest["parsers"]}
    parser = descriptors[xiaomi.SOURCE_ID]
    capture_input = {"capture_id": "synthetic-c3", "query_id": "synthetic-q3", "source_id": xiaomi.SOURCE_ID,
                     "target_kind": "vehicle", "query": history["query"], "query_key": history["query_key"],
                     "source_url": xiaomi.API_URL, "content_type": "application/json", "raw_hash": history["hashes"]["B"],
                     "byte_count": len(history["bodies"]["B"].encode("utf-8")), "observed_at": "2026-01-01T00:03:00+00:00",
                     "storage_kind": "object_store", "original_parser_version": xiaomi.PARSER_VERSION,
                     "original_parser_identity": None}
    baseline = {"snapshot_id": "synthetic-vs-accepted-loss", "verification_id": "synthetic-v5",
                "verified_at": "2026-01-01T00:05:00+00:00", "observed_at": "2026-01-01T00:05:00+00:00",
                "raw_hash": history["hashes"]["Q"], "source_url": xiaomi.API_URL,
                "parser_version": xiaomi.PARSER_VERSION, "parser_identity": None,
                "selected_at": "2026-01-01T00:09:00+00:00", "payload": history["payloads"]["Q"]}
    parser_identity = {"version": parser["parser_version"], "digest": parser["parser_digest"], "bundle_id": manifest["bundle_id"]}
    bindings = [{"input": capture_input, "reference": {"snapshot_id": "synthetic-vs-b", "raw_hash": history["hashes"]["B"],
                 "observed_at": "2026-01-01T00:03:00+00:00", "payload": history["payloads"]["B"]}}]
    evaluation = {"source_id": xiaomi.SOURCE_ID, "target_bundle_id": manifest["bundle_id"],
                  "control_bundle_id": manifest["bundle_id"], "deployment_revision": 1, "bindings": bindings}
    reparse_request = ReparseCreate(mode="history", capture_id="synthetic-c3", parser_version=parser["parser_version"],
                                    parser_digest=parser["parser_digest"], bundle_id=manifest["bundle_id"])
    evaluation_request = EvaluationCreate(mode="history", source_id=xiaomi.SOURCE_ID, target_bundle_id=manifest["bundle_id"],
                                          capture_ids=["synthetic-c3"], expected_deployment_revision=1)
    preview = _blocked_plan(database)
    fingerprint = preview["fingerprint"]
    with database.engine.begin() as connection:
        add = lambda table, **values: _insert(connection, base, table, **values)
        add("parser_bundles", id=manifest["bundle_id"], manifest=manifest, descriptors=descriptors,
            operator="synthetic fixture builder", reason="Frozen current source inventory; no parser execution",
            origin="builtin_bootstrap", created_at=AT + timedelta(minutes=8))
        add("parser_deployment_revisions", id="synthetic-bootstrap", source_id=xiaomi.SOURCE_ID, revision=1, state="active",
            bundle_id=manifest["bundle_id"], descriptor=parser, action="bootstrap", evaluation_review_id=None,
            rollback_revision=None, actor_session_id="local-bootstrap", idempotency_key=xiaomi.SOURCE_ID,
            request_hash=_digest({"source_id": xiaomi.SOURCE_ID, "bundle_id": manifest["bundle_id"]}),
            operator="synthetic fixture builder", reason="Synthetic historical bootstrap registration; no live activation",
            created_at=AT + timedelta(minutes=8))
        add("reparse_runs", id="synthetic-reparse-pending", actor_session_id=SESSION,
            idempotency_key="00000000-0000-4000-8000-000000000101",
            request_hash=_digest(reparse_request.model_dump(exclude_none=True)), capture_id="synthetic-c3", input=capture_input,
            parser=parser_identity, baseline=baseline,
            input_hash=_digest({"input": capture_input, "parser": parser_identity, "baseline": baseline}),
            created_at=AT + timedelta(minutes=9))
        add("parser_evaluations", id="synthetic-evaluation-pending", actor_session_id=SESSION,
            idempotency_key="00000000-0000-4000-8000-000000000102", request_hash=_digest(evaluation_request.model_dump()),
            input_hash=_digest(evaluation), created_at=AT + timedelta(minutes=9), **evaluation)
        add("offline_pack_plans", id="synthetic-offline-plan", package_id="synthetic-offline-package",
            actor_session_id=SESSION, fingerprint=fingerprint, preview=preview, content_hash=None, byte_count=preview["measured_bytes"],
            created_at=AT + timedelta(minutes=9), expires_at=AT + timedelta(minutes=19))


def _seed_relation_and_interest(database, base, history):
    """Fixed sentinel plus production read-only projections against this private DB."""
    from tire_api.db import TireVariant
    from tire_api.domain import IDENTITY_CONTRACT_VERSION, VariantInput
    from tire_api.service import business_facts
    from tire_api.identity_contract import _new_binding
    from tire_api.fitment_relations import RelationDecision, RelationPreviewRequest, RelationSelection, preview
    from tire_api.fitment_relation_models import FitmentRelationRevision
    from tire_api.interest_events import freeze
    from tire_api.vehicles import VehicleSnapshot

    fit = history["payloads"]["B"]["fitments"][0]
    parsed = VariantInput(brand="Synthetic", model="Synthetic Tire", manufacturer_product_code="SYNTHETIC-001",
                         region="CN", size=fit["front"]["size"], load_index="101", speed_rating="Y", xl=True, hl=False,
                         oe_mark="SYNTH", acoustic_technology="Synthetic acoustic", run_flat=False,
                         facts={"product_code_type": "MSPN", "utqg_treadwear": 300})
    source = "synthetic-tire-source"
    tire_query = {"brand": "Synthetic", "model": "Synthetic Tire"}
    query_key = _digest(tire_query)
    identity_key, status = parsed.identity_key(source, query_key, 0)
    variant_id, snapshot_id, fact_id = "synthetic-tire", "synthetic-tire-snapshot", "synthetic-tire-fact"
    member = {**parsed.model_dump(), "id": variant_id, "identity_key": identity_key, "identity_status": status, "fact_version": 1}
    body = _json({"synthetic": True, "variants": [parsed.model_dump()]})
    facts = business_facts(parsed.facts)
    identity_binding = _new_binding(variant_id=variant_id, key=identity_key, identity=parsed.identity(), status=status,
        origin="source_observation", proof={"snapshot_id": snapshot_id, "source_id": source, "query_key": query_key,
        "row_index": 0, "legacy_key": parsed.legacy_identity_key(source, query_key, 0)[0]}, binding_id="synthetic-identity-binding")
    with database.engine.begin() as connection:
        add = lambda table, **values: _insert(connection, base, table, **values)
        add("query_runs", id="synthetic-tire-query", session_id=SESSION, source_id=source, query_key=query_key,
            query=tire_query, selection_filters=None, source_access_generation=None, fallback_policy="never",
            state="live", reason=None, created_at=AT + timedelta(minutes=2))
        add("tire_variants", id=variant_id, identity_key=identity_key, identity=parsed.identity(),
            identity_status=status, created_at=AT + timedelta(minutes=2))
        add("snapshots", id=snapshot_id, source_id=source, query_key=query_key,
            source_url="https://synthetic.invalid/tire", raw_hash=_hash(body.encode("utf-8")), body=body,
            content_type="application/json", parser_version="synthetic-fixture@1", parser_identity=None,
            identity_contract_version=IDENTITY_CONTRACT_VERSION, observed_at=AT + timedelta(minutes=2),
            etag=None, last_modified=None, parsed_variants=[member])
        add("fact_versions", id=fact_id, variant_id=variant_id, source_id=source, snapshot_id=snapshot_id,
            facts=facts, facts_hash=_digest(facts), version=1, observed_at=AT + timedelta(minutes=2))
        add("verifications", id="synthetic-tire-verification", snapshot_id=snapshot_id, query_id="synthetic-tire-query",
            source_id=source, query_key=query_key, status="ok", parser_identity=None, etag=None, last_modified=None,
            verified_at=AT + timedelta(minutes=2, seconds=1))
        add("variant_identity_bindings", **{column.name: getattr(identity_binding, column.name)
            for column in base.metadata.tables["variant_identity_bindings"].columns if column.name != "created_at"},
            created_at=AT + timedelta(minutes=2))
    selection = RelationSelection(vehicle_id="xiaomi-su7-current", vehicle_snapshot_id="synthetic-vs-accepted-loss",
        trim_id=fit["trim_id"], wheel_option_id=fit["id"], axle="front", variant_id=variant_id,
        tire_snapshot_id=snapshot_id, fact_version_id=fact_id)
    with database.sessions() as session:
        proposed = preview(session, RelationPreviewRequest(mode="history", action="create", selection=selection))
        _require(proposed["can_submit"], "synthetic_relation_not_submittable")
        vehicle_evidence, tire_evidence = proposed["vehicle_evidence"], proposed["tire_evidence"]
        relation_binding, checks = proposed["binding"], proposed["checks"]
        scope = {key: value for key, value in relation_binding["vehicle"]["scope"].items()
                 if key not in {"availability", "requirements"}}
        _require(session.get(TireVariant, variant_id) is not None, "sentinel_identity_missing")
        vehicle = session.get(VehicleSnapshot, "synthetic-vs-b")
        vehicle_event = freeze(session, "vehicle", vehicle)
    decision = RelationDecision(mode="history", action="create", selection=selection, expected_revision=0,
        expected_fingerprint=proposed["fingerprint"], operator="synthetic fixture builder",
        reason="Synthetic historical pending relation; not reviewed official fitment", acknowledged=True, acknowledge_unknowns=True)
    after = {"revision": 1, "review_state": "pending_review", "selection": selection.model_dump(),
             "binding_hash": _digest(relation_binding), "vehicle_evidence": vehicle_evidence, "tire_evidence": tire_evidence}
    with database.engine.begin() as connection:
        add = lambda table, **values: _insert(connection, base, table, **values)
        add("fitment_relations", id="synthetic-relation", vehicle_id=selection.vehicle_id, trim_id=selection.trim_id,
            wheel_option_id=selection.wheel_option_id, axle=selection.axle, scope=scope, created_at=AT + timedelta(minutes=10))
        add("fitment_relation_revisions", id="synthetic-relation-r1", relation_id="synthetic-relation", revision=1,
            action="create", review_state="pending_review", selection=selection.model_dump(), vehicle_evidence=vehicle_evidence,
            tire_evidence=tire_evidence, binding=relation_binding, binding_hash=_digest(relation_binding), checks=checks,
            before=None, after=after, acknowledged_unknowns=True, operator="synthetic fixture builder",
            reason="Synthetic historical pending relation; not reviewed official fitment", actor_session_id=SESSION,
            idempotency_key="00000000-0000-4000-8000-000000000103", request_hash=_digest(decision.model_dump()),
            created_at=AT + timedelta(minutes=10))
    with database.sessions() as session:
        relation_event = freeze(session, "fitment", session.get(FitmentRelationRevision, "synthetic-relation-r1"))
    with database.engine.begin() as connection:
        for domain, origin, payload in (("vehicle", "synthetic-vs-b", vehicle_event),
                                        ("fitment", "synthetic-relation-r1", relation_event)):
            _require(payload["after"]["evidence_valid"], "synthetic_event_evidence_invalid")
            _insert(connection, base, "interest_events", id=payload["id"], domain=domain, origin_id=origin,
                    observed_at=datetime.fromisoformat(payload["observed_at"]), event_hash=payload["event_hash"], payload=payload)


def _blocked_plan(database):
    # Resolve real private history; deliberately requesting a quarantine as an
    # accepted snapshot is rejected. This supplies a truthful blocked plan, not
    # a hand-invented omission or a completed OfflinePack.
    from tire_api.offline_packs import CAPACITY, CanonicalJSON, OfflineScope
    from tire_api.offline_evidence import documents, resolve_scope
    from tire_api.field_authority import policy_catalog
    from tire_api.recall_evidence import recall_policy_descriptor
    scope = OfflineScope(garage={"include": False}, watchlist={"include": False},
                         recent={"include": False, "limit": 0}, references=[
        {"kind": "vehicle", "snapshot_id": "synthetic-vs-b", "verification_id": "synthetic-v3"},
        {"kind": "vehicle", "snapshot_id": "synthetic-quarantine"},
    ]).model_dump()
    for reference in scope["references"]:
        if reference.get("verification_id") is None:
            reference.pop("verification_id", None)
    with database.sessions() as session:
        contexts, members, omissions, counts = resolve_scope(session, None, scope, SESSION,
                                                             limits=CAPACITY, pack_schema="offline-pack@2")
    _require(len(members) == 1 and any(item["blocking"] and item["reason"] == "offline_vehicle_snapshot_missing"
                                     for item in omissions), "offline_blocking_case_invalid")
    docs = documents(contexts, members)
    counts.update(distinct_evidence=len(members), searchable_documents=len(docs))
    owner = _digest({"namespace": "offline-owner-scope@1", "session": SESSION})
    envelope = {"schema": "offline-pack@2", "package_id": "synthetic-offline-package",
                "created_at": "2026-01-01T00:09:00+00:00", "owner_scope_id": owner, "privacy_class": "private",
                "data_state": "local_snapshot", "source_refresh_performed": False, "base_pack_id": None, "scope": scope,
                "contracts": {"offline_policy": CAPACITY["version"], "field_policy": policy_catalog(),
                              "recall_policy": recall_policy_descriptor()},
                "contexts": contexts, "members": members, "documents": docs, "omissions": omissions}
    writer = CanonicalJSON()
    _, fingerprint, _ = writer.measure(envelope)
    envelope["plan_fingerprint"] = fingerprint
    measured, content_hash, _ = writer.measure(envelope)
    _require(measured <= CAPACITY["max_package_bytes"], "unexpected_offline_capacity_limit")
    return {"schema": "offline-pack-plan@2", "id": "synthetic-offline-plan", "package_id": "synthetic-offline-package",
            "state": "blocked", "created_at": envelope["created_at"], "expires_at": "2026-01-01T00:19:00+00:00",
            "fingerprint": fingerprint, "owner_scope_id": owner, "privacy_class": "private", "requested_scope": scope,
            "base_pack_id": None, "resolved": [{key: item[key] for key in
                ("key", "reference", "member_reasons", "privacy_class", "raw_included")} for item in members],
            "contexts": contexts, "documents": docs, "omissions": omissions, "counts": counts,
            "measured_bytes": measured, "content_sha256": content_hash, "capacity": CAPACITY.copy(), "can_confirm": False,
            "privacy_notice": "Garage 属于本地工作区；关注项和最近查询属于当前会话。导出包含私人用户上下文。",
            "rights_notice": "仅保存结构化事实和证据短摘录；排除原始全文、图片与链接媒体。保存声明不等于转载许可。",
            "diff": {"added": sorted(item["key"] for item in members), "removed": [], "changed": []}}


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _cell(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {"type": "blob", "hex": value.hex()}
    if isinstance(value, float):
        _require(math.isfinite(value), "nonfinite_sql_value")
        return {"type": "real", "value": value}
    return {"type": "integer" if isinstance(value, int) else "text", "value": value}


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    if isinstance(value, str):
        _require("\x00" not in value, "nul_text_not_supported")
        return "'" + value.replace("'", "''") + "'"
    _require(type(value) is int or type(value) is float and math.isfinite(value), "unsupported_sql_value")
    return repr(value)


def _rows(connection, table):
    return sorted(connection.execute("SELECT * FROM " + _identifier(table)).fetchall(),
                  key=lambda row: _json([_cell(value) for value in row]))


def _inventory(connection):
    objects = []
    table_kinds = {row[1]: row[2] for row in connection.execute("PRAGMA table_list") if row[0] == "main"}
    for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"):
        category = ("shadow" if table_kinds.get(name) == "shadow" else "virtual" if table_kinds.get(name) == "virtual"
                    else "autoindex" if kind == "index" and sql is None else kind)
        objects.append({"type": kind, "name": name, "table": table, "category": category, "sql": sql})
    tables = {}
    for item in objects:
        if item["type"] != "table":
            continue
        name = item["name"]
        rows = _rows(connection, name)
        tables[name] = {"columns": [list(row) for row in connection.execute("PRAGMA table_xinfo(" + _identifier(name) + ")")],
                        "foreign_keys": sorted([list(row) for row in connection.execute("PRAGMA foreign_key_list(" + _identifier(name) + ")")]),
                        "row_count": len(rows), "rows_sha256": _digest([[_cell(value) for value in row] for row in rows])}
    return {"schema_objects": objects, "tables": tables,
            "versions": [row[0] for row in connection.execute("SELECT version FROM tire_schema_versions ORDER BY version")]}


def _assert_023(connection, inventory):
    _require(inventory["versions"] == VERSIONS, "not_fixed_023_versions")
    inbound = []
    for table, info in inventory["tables"].items():
        for fk in info["foreign_keys"]:
            if fk[2] == "vehicle_snapshots":
                inbound.append((table, fk[3], fk[4]))
            _require(fk[2] != "vehicle_quarantines", "unexpected_quarantine_fk")
    _require(sorted(inbound) == [("vehicle_quarantines", "previous_snapshot_id", "id"),
                                 ("vehicle_verifications", "snapshot_id", "id"),
                                 ("vehicle_wheel_fitments", "snapshot_id", "id")], "snapshot_fk_contract_changed")
    for table in ("vehicle_snapshots", "vehicle_quarantines"):
        columns = {column[1]: column for column in inventory["tables"][table]["columns"]}
        _require(columns["body"][3] == 1 and not {"body_encoding", "raw_capture_id"} & columns.keys(), "not_023_vehicle_shape")
    triggers = [obj for obj in inventory["schema_objects"] if obj["type"] == "trigger"]
    _require(len(triggers) == 57 and len({obj["table"] for obj in triggers}) == 19, "trigger_contract_changed")
    _require(not any(obj["table"].startswith("vehicle_") for obj in triggers), "unexpected_vehicle_trigger")
    _require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "integrity_check_failed")
    _require(connection.execute("PRAGMA foreign_key_check").fetchall() == [], "foreign_key_check_failed")
    for table in ("users", "external_api_keys", "external_api_key_revocations", "external_api_key_operations",
                  "external_api_key_minutes", "offline_packs", "reparse_completions", "parser_evaluation_completions",
                  "reparse_reviews", "parser_evaluation_reviews", "parser_selections", "parser_executions"):
        _require(inventory["tables"][table]["row_count"] == 0, "credential_or_completed_work_rows_forbidden")


def _records(connection, table):
    cursor = connection.execute("SELECT * FROM " + _identifier(table))
    try:
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _assert_history(connection, assets):
    """Independent stdlib checks for relational and serialized evidence bindings."""
    captures = {row["id"]: row for row in _records(connection, "raw_captures")}
    snapshots = {row["id"]: row for row in _records(connection, "vehicle_snapshots")}
    verifications = {row["id"]: row for row in _records(connection, "vehicle_verifications")}
    queries = {row["id"]: row for row in _records(connection, "query_runs")}
    capture_objects = {row["capture_id"]: row["raw_hash"] for row in _records(connection, "capture_objects")}
    objects = {row["raw_hash"]: row for row in _records(connection, "evidence_objects")}
    _require(len(captures) == 6 and len(snapshots) == 4 and len(verifications) == 5
             and len(capture_objects) == 6 and len(objects) == 4, "core_history_cardinality_changed")
    asset_keys = set()
    for capture in captures.values():
        raw = capture["raw_body"]
        raw_hash = _hash(raw)
        _require(raw_hash == capture["raw_hash"] == capture_objects[capture["id"]]
                 and len(raw) == capture["byte_count"] == objects[raw_hash]["byte_count"], "capture_bytes_invalid")
        query = queries[capture["query_id"]]
        _require(query["source_id"] == capture["source_id"] and query["query_key"] == capture["query_key"]
                 == _digest(json.loads(query["query"])), "capture_query_binding_invalid")
        asset_key = "objects/sha256/" + raw_hash[:2] + "/" + raw_hash
        asset_keys.add(asset_key)
        item = assets[asset_key]
        _require(item["sha256"] == raw_hash and item["bytes"] == len(raw)
                 and base64.b64decode(item["base64"], validate=True) == raw, "capture_asset_missing_or_changed")
    _require({key for key in assets if key.startswith("objects/")} == asset_keys, "unexpected_object_assets")
    _require(captures["synthetic-c1"]["raw_body"] == captures["synthetic-c2"]["raw_body"]
             and captures["synthetic-c1"]["raw_body"] != captures["synthetic-c3"]["raw_body"], "repeat_capture_case_invalid")
    _require(snapshots["synthetic-vs-a"]["fact_hash"] == snapshots["synthetic-vs-b"]["fact_hash"]
             and snapshots["synthetic-vs-a"]["fact_version"] == snapshots["synthetic-vs-b"]["fact_version"] == 1
             and snapshots["synthetic-vs-accepted-loss"]["fact_version"] == 2
             and snapshots["synthetic-vs-accepted-loss"]["fact_hash"] != snapshots["synthetic-vs-b"]["fact_hash"],
             "fact_history_case_invalid")
    for snapshot in snapshots.values():
        _require(_hash(snapshot["body"].encode("utf-8")) == snapshot["raw_hash"], "snapshot_bytes_changed")
        _require(snapshot["parser_identity"] in (None, "null"), "legacy_parser_identity_changed")
    _require(verifications["synthetic-v1"]["snapshot_id"] == verifications["synthetic-v2"]["snapshot_id"]
             and not any(row["query_id"] == "synthetic-q0" for row in captures.values()), "legacy_or_repeat_binding_invalid")
    quarantine = _records(connection, "vehicle_quarantines")[0]
    review = _records(connection, "quarantine_reviews")[0]
    approval = _records(connection, "quarantine_approval_uses")[0]
    qrun = queries[quarantine["query_id"]]
    expected_binding = _digest({"target": "vehicle", "source": quarantine["source_id"], "query_key": qrun["query_key"],
        "baseline": quarantine["previous_snapshot_id"], "raw_hash": quarantine["raw_hash"], "url": quarantine["source_url"],
        "parser": quarantine["parser_version"], "content_type": quarantine["content_type"],
        "payload": json.loads(quarantine["payload"]), "quality": json.loads(quarantine["quality"])})
    _require(review["quarantine_id"] == quarantine["id"] and review["binding_hash"] == expected_binding
             and approval["review_id"] == review["id"] and approval["query_id"] == "synthetic-q5"
             and captures["synthetic-c4"]["raw_body"] == captures["synthetic-c5"]["raw_body"]
             == quarantine["body"].encode("utf-8"), "quarantine_approval_binding_invalid")
    rejected = _records(connection, "rejected_observations")[0]
    _require(rejected["raw_body"] == captures["synthetic-c6"]["raw_body"] and rejected["query_id"] == "synthetic-q6"
             and not any(row["query_id"] == "synthetic-q6" for row in verifications.values()), "rejection_was_accepted")
    garage = json.loads(_records(connection, "garage_revisions")[0]["fitment_reference"])
    garage_snapshot = snapshots[garage["snapshot_id"]]
    _require(garage["raw_hash"] == garage_snapshot["raw_hash"] and any(fit["id"] == garage["fitment_id"]
             for fit in json.loads(garage_snapshot["payload"])["fitments"]), "garage_reference_invalid")
    runs = _records(connection, "reparse_runs")
    _require(len(runs) == 1, "pending_reparse_count_invalid")
    run = runs[0]
    run_input, parser, baseline = (json.loads(run[key]) for key in ("input", "parser", "baseline"))
    _require(run["input_hash"] == _digest({"input": run_input, "parser": parser, "baseline": baseline})
             and run["capture_id"] == run_input["capture_id"] == "synthetic-c3"
             and run_input["raw_hash"] == captures[run["capture_id"]]["raw_hash"]
             and baseline["payload"] == json.loads(snapshots[baseline["snapshot_id"]]["payload"])
             and verifications[baseline["verification_id"]]["snapshot_id"] == baseline["snapshot_id"], "reparse_binding_invalid")
    bundles = {row["id"]: row for row in _records(connection, "parser_bundles")}
    _require(len(bundles) == 1 and parser["bundle_id"] in bundles, "pending_bundle_binding_invalid")
    bundle_assets = set()
    for identifier, bundle in bundles.items():
        manifest = json.loads(bundle["manifest"])
        descriptors = json.loads(bundle["descriptors"])
        _require(identifier == manifest["bundle_id"] == _digest({key: value for key, value in manifest.items()
                  if key != "bundle_id"}), "bundle_manifest_hash_invalid")
        prefix = "bundles/sha256/" + identifier + "/"
        bundle_assets.add(prefix + "manifest.json")
        _require(base64.b64decode(assets[prefix + "manifest.json"]["base64"], validate=True) == _json(manifest).encode("utf-8"),
                 "bundle_manifest_asset_invalid")
        for name, metadata in manifest["files"].items():
            key = prefix + "package/tire_api/" + name
            bundle_assets.add(key)
            item = assets[key]
            _require(item["sha256"] == metadata["sha256"] and item["bytes"] == metadata["byte_count"], "bundle_file_asset_invalid")
        descriptor = descriptors[run_input["source_id"]]
        _require(parser["digest"] == descriptor["parser_digest"] and parser["version"] == descriptor["parser_version"],
                 "reparse_descriptor_mismatch")
    _require({key for key in assets if key.startswith("bundles/")} == bundle_assets, "unexpected_bundle_assets")
    evaluation = _records(connection, "parser_evaluations")[0]
    evaluation_hash = {key: evaluation[key] for key in ("source_id", "target_bundle_id", "control_bundle_id", "deployment_revision")}
    evaluation_hash["bindings"] = json.loads(evaluation["bindings"])
    _require(evaluation["input_hash"] == _digest(evaluation_hash)
             and evaluation_hash["bindings"][0]["input"] == run_input
             and evaluation["target_bundle_id"] in bundles and evaluation["control_bundle_id"] in bundles,
             "evaluation_binding_invalid")
    deployments = _records(connection, "parser_deployment_revisions")
    _require(len(deployments) == 1, "synthetic_bootstrap_count_invalid")
    deployment = deployments[0]
    _require(deployment["action"] == "bootstrap" and deployment["revision"] == evaluation["deployment_revision"] == 1
             and deployment["state"] == "active" and deployment["bundle_id"] == evaluation["control_bundle_id"]
             and deployment["evaluation_review_id"] is None and deployment["rollback_revision"] is None
             and deployment["request_hash"] == _digest({"source_id": deployment["source_id"], "bundle_id": deployment["bundle_id"]})
             and json.loads(deployment["descriptor"]) == json.loads(bundles[deployment["bundle_id"]]["descriptors"])[deployment["source_id"]],
             "synthetic_bootstrap_binding_invalid")
    relation = _records(connection, "fitment_relation_revisions")[0]
    selection, vehicle, tire, binding = (json.loads(relation[key]) for key in ("selection", "vehicle_evidence", "tire_evidence", "binding"))
    _require(relation["binding_hash"] == _digest(binding) and relation["review_state"] == "pending_review"
             and vehicle["provenance"]["snapshot_id"] == selection["vehicle_snapshot_id"]
             and vehicle["provenance"]["raw_hash"] == snapshots[selection["vehicle_snapshot_id"]]["raw_hash"],
             "relation_vehicle_binding_invalid")
    tire_snapshot = _records(connection, "snapshots")[0]
    fact = _records(connection, "fact_versions")[0]
    _require(selection["tire_snapshot_id"] == tire_snapshot["id"] == tire["provenance"]["snapshot_id"]
             and _hash(tire_snapshot["body"].encode("utf-8")) == tire_snapshot["raw_hash"]
             and selection["fact_version_id"] == fact["id"] == tire["fact_version_id"]
             and fact["facts_hash"] == _digest(json.loads(fact["facts"])) == tire["facts_hash"], "relation_tire_binding_invalid")
    events = _records(connection, "interest_events")
    _require(len(events) == 2, "interest_sentinel_count_invalid")
    for event in events:
        payload = json.loads(event["payload"])
        _require(payload["event_hash"] == event["event_hash"] == _digest({key: value for key, value in payload.items()
                 if key != "event_hash"}) and payload["after"]["evidence_valid"], "interest_event_hash_invalid")
        for reference in payload["evidence"]:
            sid = reference["snapshot_id"]
            if sid is not None:
                _require(sid in snapshots or sid == tire_snapshot["id"], "interest_snapshot_reference_invalid")
    plan = _records(connection, "offline_pack_plans")[0]
    preview = json.loads(plan["preview"])
    _require(plan["content_hash"] is None and preview["state"] == "blocked" and not preview["can_confirm"]
             and all(not preview["requested_scope"][key]["include"] for key in ("garage", "watchlist", "recent"))
             and plan["fingerprint"] == preview["fingerprint"] and plan["byte_count"] == preview["measured_bytes"]
             and len(preview["resolved"]) == 1 and any(item["reason"] == "offline_vehicle_snapshot_missing" and item["blocking"]
             for item in preview["omissions"]), "blocked_offline_plan_invalid")
    reference = preview["resolved"][0]["reference"]
    _require(reference["snapshot_id"] in snapshots and verifications[reference["verification_id"]]["snapshot_id"]
             == reference["snapshot_id"], "offline_reference_invalid")
    for item in assets.values():
        raw = base64.b64decode(item["base64"], validate=True)
        _require(len(raw) == item["bytes"] and _hash(raw) == item["sha256"], "embedded_asset_bytes_invalid")


def _static_sql(connection, inventory):
    objects = inventory["schema_objects"]
    order = {"table": 0, "virtual": 1, "index": 2, "view": 3, "trigger": 4}
    ddl = [obj for obj in objects if obj["sql"] is not None and obj["category"] in order]
    ddl.sort(key=lambda obj: (order[obj["category"]], obj["name"]))
    schema = "-- Frozen current 023 schema; no custom overlays.\n" + "\n".join(obj["sql"].rstrip(";") + ";" for obj in ddl) + "\n"
    seed = ["-- Synthetic historical rows only. FTS shadow rows are recreated by FTS5.", "BEGIN;"]
    for obj in sorted(objects, key=lambda obj: obj["name"]):
        if obj["type"] != "table" or obj["category"] == "shadow":
            continue
        name = obj["name"]
        columns = [row[1] for row in connection.execute("PRAGMA table_info(" + _identifier(name) + ")")]
        for row in _rows(connection, name):
            seed.append("INSERT INTO " + _identifier(name) + " (" + ",".join(map(_identifier, columns))
                        + ") VALUES (" + ",".join(_literal(value) for value in row) + ");")
    seed.append("COMMIT;")
    return schema, "\n".join(seed) + "\n"


def _private_assets(private):
    values = {}
    for folder in (private / "objects", private / "bundles"):
        _require(folder.is_dir(), "private_asset_root_missing")
        for path in sorted(folder.rglob("*")):
            _plain(path)
            if path.is_file():
                data = path.read_bytes()
                name = path.relative_to(private).as_posix()
                values[name] = {"sha256": _hash(data), "bytes": len(data), "base64": base64.b64encode(data).decode("ascii")}
    _require(any(name.startswith("objects/sha256/") for name in values)
             and any(name.startswith("bundles/sha256/") for name in values), "private_asset_inventory_empty")
    return values


def run_capture(frozen_source_root, source_manifest, output_root):
    """Capture private schema/data from verified frozen source; do not publish."""
    root = _verified_source(frozen_source_root, source_manifest)
    output, private, path = _output(output_root, "capture")
    _require(not output.resolve().is_relative_to(root.resolve()), "output_inside_source_forbidden")
    _require(not any(name == "tire_api" or name.startswith("tire_api.") for name in sys.modules), "preloaded_production_package")
    _require(Path(os.environ.get("TI_PARSER_BUNDLE_ROOT", "")).resolve() == (private / "bundles").resolve(),
             "private_bundle_root_required")
    _require(Path(os.environ.get("TI_OBJECT_STORE_ROOT", "")).resolve() == (private / "objects").resolve(),
             "private_object_root_required")
    old_path = list(sys.path)
    database = None
    connection = None
    try:
        sys.path.insert(0, str(root / "apps/api"))
        modules, table_names = _model_modules(root)
        for module in modules:
            importlib.import_module(module)
        from tire_api.db import Base, Database
        _require(set(Base.metadata.tables) == table_names, "metadata_inventory_mismatch")
        _check_imports(root, source_manifest)
        database = Database("sqlite:///" + path.as_posix())
        database.initialize()
        history = _seed_core(database, Base)
        _seed_relation_and_interest(database, Base, history)
        _seed_pending(database, Base, history)
        database.close()
        database = None
        connection = sqlite3.connect(str(path))
        inventory = _inventory(connection)
        _assert_023(connection, inventory)
        assets = _private_assets(private)
        _assert_history(connection, assets)
        schema, seed = _static_sql(connection, inventory)
        connection.close()
        connection = None
        imports = _check_imports(root, source_manifest)
        _verified_source(root, source_manifest)
        staging = output / "staging"
        staging.mkdir(exist_ok=False)
        expected = {"schema": FIXTURE_SCHEMA, "sqlite_version": sqlite3.sqlite_version,
                    "inventory": inventory, "private_assets": assets,
                    "history": {"raw_hashes": history["hashes"], "quarantine_binding": history["binding_hash"],
                                "quality": history["quality"], "pending_only": ["reparse", "parser_evaluation", "offline_plan"]},
                    "sql_hashes": {"schema_023.sql": _hash(schema.encode("utf-8")), "seed_023.sql": _hash(seed.encode("utf-8"))}}
        _write(staging / "schema_023.sql", schema)
        _write(staging / "seed_023.sql", seed)
        _write(staging / "expected_023.json", _json(expected) + "\n")
        _write(staging / "source-index.json", _json({"schema": FIXTURE_SCHEMA, "frozen_source_manifest": source_manifest,
                                                     "model_modules": modules, "imported_modules": imports}) + "\n")
        _write(staging / "README.md", "# Frozen current 023 private baseline\n\n"
               "A private baseline generated from frozen current 023 source, containing synthetic historical data. "
               "This is not a normal-database backup or a retained historical production database.\n\n"
               "Schema includes all 134 ORM tables, the migration ledger, FTS5 virtual/shadow tables, indexes, "
               "and existing triggers. No custom schema overlays are included. Vehicle immutability remains an ORM contract.\n\n"
               "Seed data contains legacy text-only vehicle evidence, repeated capture bytes, changed raw bytes with unchanged facts, "
               "quarantine approval/reuse, parser rejection, garage references and pending work. No Parser run or release is completed. "
               "One synthetic historical bootstrap registration has database state=active; no bootstrap/activate command was run, "
               "and no normal application was enabled. The blocked offline plan deliberately rejects a quarantine as accepted evidence. "
               "All users and credential inventories remain empty. Embedded object/bundle bytes are private synthetic/source assets.\n\n"
               "Replay uses only these static SQL/JSON files through the separately reviewed gate driver. It must not import tire_api "
               "or SQLAlchemy, initialize production metadata, contact a network or open a normal database. "
               "Gate 1 does not authorize schema 024, normal-database upgrade, HTTP acceptance, or real-source acceptance.\n")
        return {"success": True, "table_count": len(inventory["tables"]), "file_count": len(PRODUCTS)}
    finally:
        if connection is not None:
            connection.close()
        if database is not None:
            database.close()
        sys.path[:] = old_path


def run_replay(fixture_root, output_root):
    """Recreate second private database from reviewed static files only."""
    _require(not any(name == "tire_api" or name.startswith("tire_api.") or name == "sqlalchemy"
                     or name.startswith("sqlalchemy.") for name in sys.modules), "replay_production_import_forbidden")
    fixture = _plain(fixture_root)
    output, private, path = _output(output_root, "replay")
    _require(not output.resolve().is_relative_to(fixture.resolve()), "replay_output_inside_fixture")
    expected = json.loads((fixture / "expected_023.json").read_text(encoding="utf-8"))
    _require(expected["schema"] == FIXTURE_SCHEMA and expected["sqlite_version"] == sqlite3.sqlite_version,
             "replay_environment_mismatch")
    sql = {}
    for name in ("schema_023.sql", "seed_023.sql"):
        data = (fixture / name).read_bytes()
        _require(_hash(data) == expected["sql_hashes"][name], "static_sql_changed")
        sql[name] = data.decode("utf-8")
    connection = None
    try:
        connection = sqlite3.connect(str(path))
        connection.execute("PRAGMA foreign_keys=OFF").close()
        connection.executescript(sql["schema_023.sql"])
        connection.executescript(sql["seed_023.sql"])
        connection.execute("PRAGMA foreign_keys=ON").close()
        _require(connection.execute("PRAGMA foreign_keys").fetchone() == (1,), "foreign_keys_not_enabled")
        inventory = _inventory(connection)
        _assert_023(connection, inventory)
        _assert_history(connection, expected["private_assets"])
        _require(inventory == expected["inventory"], "static_replay_mismatch")
        connection.close()
        connection = None
        for name, item in expected["private_assets"].items():
            relative = _relative(name)
            _require(relative.parts[0] in {"objects", "bundles"}, "asset_root_invalid")
            destination = _plain(private.joinpath(*relative.parts))
            _require(destination.resolve().is_relative_to(private.resolve()), "asset_escape_forbidden")
            data = base64.b64decode(item["base64"], validate=True)
            _require(len(data) == item["bytes"] and _hash(data) == item["sha256"], "asset_integrity_failed")
            destination.parent.mkdir(parents=True, exist_ok=True)
            _write(destination, data)
        _require(not any(name == "tire_api" or name.startswith("tire_api.") or name == "sqlalchemy"
                         or name.startswith("sqlalchemy.") for name in sys.modules), "replay_production_import_forbidden")
        _write(output / "replay-equivalence.json", _json({"schema": FIXTURE_SCHEMA, "success": True,
               "inventory_sha256": _digest(inventory), "tables": len(inventory["tables"]),
               "assets": len(expected["private_assets"]), "static_only": True}) + "\n")
        return {"success": True, "table_count": len(inventory["tables"]), "asset_count": len(expected["private_assets"])}
    finally:
        if connection is not None:
            connection.close()
