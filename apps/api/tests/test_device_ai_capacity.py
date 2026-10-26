"""Real default-limit byte decoding and full projection; no main or services."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from device_ai_capacity_corpus import CORPUS, CapacityCorpus, check_bytes
from tire_api.device_ai_projection import (
    FrozenPackBinding, ProjectionError, canonical_exact_json, exact_digest,
    parse_exact_json, project_offline_pack,
)

RECIPES = CORPUS.read_json("boundary-recipes.json")
FORMAL = CORPUS.read_json("formal-package.json")
CLOSURE = CORPUS.read_json("closure-package.json")
FINGERPRINTS = CORPUS.read_json("closure-fingerprints.json")


@pytest.mark.parametrize("case", RECIPES["cases"], ids=lambda c: c["id"])
def test_real_default_capacity_parser(case):
    raw = CORPUS.expand(case)
    expected = case["expected"]
    if expected["state"] == "rejected":
        with pytest.raises(ProjectionError) as error:
            parse_exact_json(raw)
        assert error.value.code == expected["error_code"]
    else:
        canonical = canonical_exact_json(parse_exact_json(raw))
        assert canonical == expected["canonical_text"].encode("utf-8")
        assert canonical.hex() == expected["canonical_utf8_hex"]
        assert hashlib.sha256(canonical).hexdigest() == expected["canonical_sha256"]


@pytest.mark.parametrize("case", FORMAL["cases"], ids=lambda c: c["id"])
def test_formal_package_at_real_byte_boundary(case):
    raw = CORPUS.formal_bytes(FORMAL, case)
    request = CORPUS.read_json(FORMAL["projection_input"])
    binding = FrozenPackBinding(**{**request["binding"], "sha256": case["input_sha256"], "byte_count": len(raw)})
    if case["expected"]["state"] == "rejected":
        with pytest.raises(ProjectionError) as error:
            project_offline_pack(raw, binding, request["selectors"])
        assert error.value.code == case["expected"]["error_code"]
        with pytest.raises(ProjectionError) as parser_error:
            parse_exact_json(raw)
        assert parser_error.value.code == "device_ai_package_capacity"
        return
    # Prove AST equivalence separately from the raw-hash-bound projection.
    assert canonical_exact_json(parse_exact_json(raw)) == canonical_exact_json(parse_exact_json(CORPUS.read_bytes(FORMAL["base_pack"])))
    result = project_offline_pack(raw, binding, request["selectors"], mode=request["mode"])
    expected = case["expected"]
    assert result.canonical_bytes == CORPUS.read_bytes(expected["projection_file"])
    check_bytes(result.canonical_bytes, expected["projection_byte_count"], expected["projection_sha256"])
    assert result.sha256 == expected["projection_sha256"] and result.member_count == 1
    inherited = parse_exact_json(CORPUS.read_bytes("projections/formal-base.canonical.json"))
    actual = parse_exact_json(result.canonical_bytes)
    assert actual["archive"]["sha256"] == case["input_sha256"]
    assert canonical_exact_json(actual["observations"]) == canonical_exact_json(inherited["observations"])


@pytest.mark.parametrize("case", CLOSURE["cases"], ids=lambda c: c["id"])
def test_real_multimember_dependency_closure(case):
    raw = CORPUS.read_bytes(case.get("package_file", CLOSURE["package_file"]))
    binding = FrozenPackBinding(**case.get("binding", CLOSURE["binding"]))
    call = lambda: project_offline_pack(raw, binding, case["selectors"], mode=case["mode"], approved_closure=case["approved_closure"])
    expected = case["expected"]
    if expected["state"] == "rejected":
        with pytest.raises(ProjectionError) as error:
            call()
        assert error.value.code == expected["error_code"]
    else:
        result = call()
        assert result.canonical_bytes == CORPUS.read_bytes(expected["projection_file"])
        check_bytes(result.canonical_bytes, expected["projection_byte_count"], expected["projection_sha256"])
        actual = parse_exact_json(result.canonical_bytes)
        assert [o["selector"] for o in actual["observations"]] == expected["resolved_closure"]
        assert result.member_count == len(expected["resolved_closure"])
        assert all(key.encode() not in result.canonical_bytes for key in CLOSURE["unselected_member_keys"])


@pytest.mark.parametrize("kind,namespace", [("preview_cases", "device-ai-local-preview@1"), ("context_cases", "device-ai-context@1")])
def test_frozen_fingerprint_preimages_use_exact_digest(kind, namespace):
    # Python currently exposes exact_digest, not the native preview helpers.
    # Literal structure is reviewed independently; this verifies its exact JSON
    # and namespaced digest through the actual Python primitive.
    for case in FINGERPRINTS[kind]:
        expected = case["expected"]
        raw = expected["canonical_text"].encode("utf-8")
        check_bytes(raw, expected["byte_count"], hashlib.sha256(raw).hexdigest())
        assert raw.hex() == expected["canonical_utf8_hex"]
        ast = parse_exact_json(raw)
        assert canonical_exact_json(ast) == raw
        assert exact_digest(ast, namespace=namespace) == expected["sha256"]
    selection = FINGERPRINTS["selection_expected"]
    assert exact_digest(sorted(FINGERPRINTS["selection_input"], key=lambda s: s["member_key"]), namespace="device-ai-selection@1") == selection["sha256"]


@pytest.mark.parametrize("change", ["missing", "corrupt", "manifest", "escape", "unbound", "recipe-length", "recipe-sha"])
def test_corpus_integrity_fails_closed(tmp_path, change):
    root = tmp_path / "corpus"
    shutil.copytree(CORPUS.root, root)
    if change == "missing":
        (root / "base-pack.json").unlink()
    elif change == "corrupt":
        raw = bytearray((root / "base-pack.json").read_bytes())
        raw[0] ^= 1
        (root / "base-pack.json").write_bytes(raw)
    elif change == "manifest":
        with (root / "manifest.json").open("ab") as output:
            output.write(b" ")
    if change in {"missing", "corrupt", "manifest"}:
        with pytest.raises((AssertionError, FileNotFoundError)):
            CapacityCorpus(root)
    elif change in {"escape", "unbound"}:
        with pytest.raises(AssertionError):
            CapacityCorpus(root).read_bytes("../base-pack.json" if change == "escape" else "unknown.json")
    else:
        case = deepcopy(RECIPES["cases"][0])
        case["input_byte_count" if change == "recipe-length" else "input_sha256"] = 1 if change == "recipe-length" else "0" * 64
        with pytest.raises(AssertionError):
            CORPUS.expand(case)


@pytest.mark.parametrize("count", [6, 7])
def test_prepare_wire_selector_and_approved_closure_cap_stays_six(count):
    from pydantic import ValidationError
    from tire_api.device_ai import DeviceAIPrepareRequest
    source = deepcopy(CLOSURE["cases"][0]["selectors"][0])
    # Wire schema does not resolve archives: use distinct synthetic selector IDs.
    selectors = [{**source, "member_key": format(i, "064x")} for i in range(1, count + 1)]
    binding = CLOSURE["binding"]
    body = {"package_id": binding["package_id"], "expected_sha256": binding["sha256"],
        "expected_byte_count": binding["byte_count"], "expected_schema": binding["schema"],
        "expected_owner_scope_id": binding["owner_scope_id"], "selectors": selectors,
        "projection_mode": "frozen_decision_closure", "approved_closure": selectors,
        "expected_projection_sha256": "a" * 64, "question_sha256": "b" * 64,
        "host_receipt_id": "11111111-2222-4333-8444-555555555555",
        "intent_id": "66666666-7777-4888-8999-aaaaaaaaaaaa"}
    if count == 6:
        assert len(DeviceAIPrepareRequest.model_validate(body).selectors) == 6
    else:
        with pytest.raises(ValidationError) as error:
            DeviceAIPrepareRequest.model_validate(body)
        assert {item["loc"][0] for item in error.value.errors()} == {"selectors", "approved_closure"}


@pytest.mark.parametrize("target", [8_388_607, 8_388_608, 8_388_609])
def test_private_archive_real_store_capacity(tmp_path, target):
    # Real immutable object writes, private sqlite file, explicit injection;
    # neither normal DB construction nor main import is involved.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from tire_api.db import Base, EvidenceObject, utcnow
    from tire_api.device_ai_archive import ArchiveLoadError, load_actor_owned_archive
    from tire_api.domain import digest
    from tire_api.object_store import FileObjectStore
    from tire_api.offline_models import OfflinePack, OfflinePackPlan
    actor = "capacity-private-owner"
    owner = digest({"namespace": "offline-owner-scope@1", "session": actor})
    source = CORPUS.read_bytes("base-pack.json")
    descriptor = CORPUS.read_json("base-descriptor.json")
    original_owner = descriptor["owner_scope_id"].encode("ascii")
    assert source.count(original_owner) == 1
    raw_base = source.replace(original_owner, owner.encode("ascii"))
    raw = raw_base + b" " * (target - len(raw_base))
    raw_sha = hashlib.sha256(raw).hexdigest()
    descriptor.update(owner_scope_id=owner, sha256=raw_sha, byte_count=target)
    engine = create_engine("sqlite:///" + (tmp_path / "capacity.sqlite").as_posix())
    store = FileObjectStore(tmp_path / "objects")
    reads = []

    class ObservedRealStore:
        def get(self, sha256, byte_count):
            reads.append((sha256, byte_count))
            return store.get(sha256, byte_count)

    try:
        Base.metadata.create_all(engine, tables=[EvidenceObject.__table__, OfflinePackPlan.__table__, OfflinePack.__table__])
        if target <= 8_388_608:
            assert store.put(raw) == raw_sha
        with Session(engine) as db:
            db.add(EvidenceObject(raw_hash=raw_sha, byte_count=target))
            now = utcnow()
            db.add(OfflinePackPlan(id=descriptor["plan_id"], package_id=descriptor["id"], actor_session_id=actor,
                fingerprint=descriptor["plan_fingerprint"], preview={}, content_hash=None, byte_count=target,
                created_at=now, expires_at=now + timedelta(minutes=10)))
            db.flush()
            db.add(OfflinePack(id=descriptor["id"], plan_id=descriptor["plan_id"], actor_session_id=actor,
                idempotency_key="capacity-private-test", request_hash="a" * 64,
                content_hash=raw_sha, byte_count=target, descriptor=descriptor))
            db.commit()
        with Session(engine) as db:
            db.info["object_store"] = ObservedRealStore()
            call = lambda: load_actor_owned_archive(db, actor_session_id=actor, package_id=descriptor["id"],
                expected_sha256=raw_sha, expected_byte_count=target, expected_schema="offline-pack@2",
                expected_owner_scope_id=owner)
            if target > 8_388_608:
                with pytest.raises(ArchiveLoadError) as error:
                    call()
                assert (error.value.code, error.value.status_code) == ("device_ai_archive_metadata_invalid", 503)
                assert reads == []
            else:
                loaded = call()
                assert loaded.raw_bytes == raw and loaded.binding.sha256 == raw_sha
                request = CORPUS.read_json("projection-input.json")
                result = project_offline_pack(loaded.raw_bytes, loaded.binding, request["selectors"])
                assert parse_exact_json(result.canonical_bytes)["archive"]["sha256"] == raw_sha
                assert result.member_count == 1 and reads == [(raw_sha, target)]
    finally:
        engine.dispose()
