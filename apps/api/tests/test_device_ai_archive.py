"""Isolated archive ownership/integrity; no app, configured store or normal DB."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, event, inspect
from sqlalchemy.orm import Session

from tire_api import device_ai_archive as archive
from tire_api.db import Base, EvidenceObject, uid, utcnow
from tire_api.device_ai_projection import FrozenPackBinding, NumberLexeme, parse_exact_json
from tire_api.domain import digest
from tire_api.object_store import FileObjectStore, MAX_OBJECT_BYTES, ObjectStoreError
from tire_api.offline_models import OfflinePack, OfflinePackPlan


ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / ".artifacts/query-fallback49/producer-v2-samples-a"
ACTOR = "synthetic-archive-owner"
FIXED_PACKS = {
    "legacy": ("0d3f27af8747b9fc390d7dbb685e8ea34fab1fbe27ef7331bc9b1a704a7ced00", 78418),
    "nonempty": ("5d5250cbd24e38d5c610ee75429ce3915b295d4e4f74dd47ede0e11bf318e862", 82981),
    "empty": ("644a5b288c0c35f728da086d9e15a02fb0547b98489a0700ad245e4d22024574", 82348),
}
FIXED_DESCRIPTORS = {
    "legacy": "58beed945e65dc23967742849a8b3fb78d5bc0809a67c13ec86562dc8c077edf",
    "nonempty": "9a647693195d96daa5a73237f108973dea4b43dce2b35eb94096ea404972629d",
    "empty": "b73693be275ca1f51ed491f2970052d7123551d547779415b904f9ff01095783",
}


class ObservedStore:
    """Observable synthetic store deliberately does not verify its return bytes."""

    def __init__(self, raw, sha256):
        self.objects = {sha256: raw}
        self.reads = []
        self.failure = None

    def get(self, sha256, byte_count):
        self.reads.append((sha256, byte_count))
        if self.failure is not None:
            raise self.failure
        if sha256 not in self.objects:
            raise ObjectStoreError("synthetic_missing/private/path/token=must-not-leak")
        return self.objects[sha256]


@dataclass
class Records:
    engine: object
    sql: list
    raw: bytes
    descriptor: dict
    store: ObservedStore

    def load(self, db, **overrides):
        values = dict(actor_session_id=ACTOR, package_id=self.descriptor["id"],
                      expected_sha256=self.descriptor["sha256"],
                      expected_byte_count=self.descriptor["byte_count"],
                      expected_schema="offline-pack@" + self.descriptor["schema"].rsplit("@", 1)[1],
                      expected_owner_scope_id=self.descriptor["owner_scope_id"])
        values.update(overrides)
        db.info["object_store"] = self.store
        return archive.load_actor_owned_archive(db, **values)


def synthetic_archive():
    owner = digest({"namespace": "offline-owner-scope@1", "session": ACTOR})
    envelope = {"schema": "offline-pack@2", "package_id": "synthetic-frozen-pack",
                "created_at": "2026-10-01T00:00:00+00:00", "owner_scope_id": owner,
                "plan_fingerprint": "b" * 64, "privacy_class": "private",
                "base_pack_id": None, "data_state": "local_snapshot", "source_refresh_performed": False,
                "scope": {}, "contracts": {}, "contexts": [], "members": [], "documents": [],
                "omissions": [], "synthetic_facts": {"archived": "old-frozen-value", "tokens": "TOKEN_FIXTURE"}}
    raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode().replace(
        b'"TOKEN_FIXTURE"', b'[9007199254740993,1.2300,5e-324,-0]')
    descriptor = {"schema": "offline-pack-descriptor@2", "id": envelope["package_id"],
                  "plan_id": "synthetic-frozen-plan", "sha256": hashlib.sha256(raw).hexdigest(),
                  "byte_count": len(raw), "owner_scope_id": owner, "privacy_class": envelope["privacy_class"],
                  "plan_fingerprint": envelope["plan_fingerprint"], "base_pack_id": None,
                  "content_created_at": envelope["created_at"], "data_state": "local_snapshot",
                  "source_refresh_performed": False,
                  "download_path": "/v1/offline-packs/synthetic-frozen-pack/download?mode=history"}
    return raw, descriptor


@pytest.fixture
def records_factory():
    engines = []

    def create(raw, descriptor, *, row_changes=None, descriptor_changes=None,
               object_size=None, include_object=True):
        engine = create_engine("sqlite:///:memory:")
        engines.append(engine)
        sql = []

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "before_cursor_execute")
        def observe(_connection, _cursor, statement, parameters, _context, _many):
            sql.append((statement, parameters))

        Base.metadata.create_all(engine, tables=[EvidenceObject.__table__, OfflinePackPlan.__table__,
                                                 OfflinePack.__table__])
        copied = deepcopy(descriptor)
        if descriptor_changes:
            copied.update(descriptor_changes)
        values = dict(id=descriptor["id"], plan_id=descriptor["plan_id"], actor_session_id=ACTOR,
                      idempotency_key=uid(), request_hash="a" * 64, content_hash=descriptor["sha256"],
                      byte_count=descriptor["byte_count"], descriptor=copied)
        if row_changes:
            values.update(row_changes)
        # Missing object is seeded without a pack FK by removing only that test
        # connection's FK enforcement, then restored before any loader operation.
        with engine.connect() as connection:
            if not include_object:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            with Session(bind=connection) as db:
                if include_object:
                    db.add(EvidenceObject(raw_hash=values["content_hash"],
                                          byte_count=descriptor["byte_count"] if object_size is None else object_size))
                    db.flush()
                now = utcnow()
                db.add(OfflinePackPlan(id=values["plan_id"], package_id=values["id"], actor_session_id=ACTOR,
                                      fingerprint="b" * 64, preview={}, content_hash=None,
                                      byte_count=values["byte_count"], created_at=now,
                                      expires_at=now + timedelta(minutes=10)))
                db.flush()
                db.add(OfflinePack(**values))
                db.flush()
                connection.commit()
            if not include_object:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
        sql.clear()
        return Records(engine, sql, raw, deepcopy(descriptor), ObservedStore(raw, descriptor["sha256"]))

    yield create
    for engine in engines:
        engine.dispose()


@pytest.fixture
def records(records_factory):
    return records_factory(*synthetic_archive())


def assert_error(records, code, status=503, *, reads=0, **overrides):
    with Session(records.engine) as db:
        with pytest.raises(archive.ArchiveLoadError) as failure:
            records.load(db, **overrides)
    assert failure.value.code == code and failure.value.status_code == status
    assert str(failure.value) == code and len(records.store.reads) == reads
    return failure.value


def test_real_server_actor_scope_and_exact_original_bytes(records):
    with Session(records.engine) as db:
        loaded = records.load(db)
        assert not db.new and not db.dirty and not db.deleted
    assert loaded.raw_bytes is records.raw
    assert loaded.binding == FrozenPackBinding(records.descriptor["id"],
        digest({"namespace": "offline-owner-scope@1", "session": ACTOR}),
        records.descriptor["sha256"], len(records.raw), "offline-pack@2")
    assert records.store.reads == [(loaded.binding.sha256, loaded.binding.byte_count)]
    assert [item.token for item in parse_exact_json(loaded.raw_bytes)["synthetic_facts"]["tokens"]] == [
        "9007199254740993", "1.2300", "5e-324", "-0"]
    assert "old-frozen-value" not in repr(loaded)
    with pytest.raises(FrozenInstanceError):
        loaded.raw_bytes = b"replacement"
    assert len(records.sql) == 2
    assert "offline_packs" in records.sql[0][0] and "evidence_objects" in records.sql[1][0]


@pytest.mark.parametrize("case", ["foreign", "missing", "foreign_bad_expected"])
def test_ownership_is_the_first_query_before_object_lookup_and_reads(records, case):
    overrides = {"actor_session_id": "foreign-actor"} if case != "missing" else {"package_id": "missing-pack"}
    if case == "foreign_bad_expected":
        overrides.update(expected_sha256="../../outside", expected_byte_count=False,
                         expected_schema={}, expected_owner_scope_id="wrong")
    assert_error(records, "device_ai_archive_not_found", 404, **overrides)
    assert len(records.sql) == 1
    statement, parameters = records.sql[0]
    assert "offline_packs.id =" in statement and "offline_packs.actor_session_id =" in statement
    assert "evidence_objects" not in statement
    assert ("foreign-actor" if case != "missing" else "missing-pack") in parameters


@pytest.mark.parametrize("field,value", [
    ("expected_sha256", "0" * 64), ("expected_sha256", "A" * 64),
    ("expected_sha256", "https://example.invalid/object"), ("expected_sha256", None),
    ("expected_byte_count", 1), ("expected_byte_count", False),
    ("expected_byte_count", 1.0), ("expected_byte_count", "500"),
    ("expected_byte_count", MAX_OBJECT_BYTES + 1), ("expected_schema", "offline-pack@1"),
    ("expected_schema", {"schema": "offline-pack@2"}),
    ("expected_owner_scope_id", "c" * 64), ("expected_owner_scope_id", None),
])
def test_client_expected_metadata_is_exact_and_never_an_object_locator(records, field, value):
    assert_error(records, "device_ai_archive_expected_mismatch", 409, **{field: value})
    assert len(records.sql) == 1


@pytest.mark.parametrize("changes", [
    {"id": "wrong"}, {"plan_id": "wrong"}, {"sha256": "0" * 64},
    {"byte_count": 1}, {"byte_count": True}, {"byte_count": 1.0},
    {"schema": "offline-pack-descriptor@0"}, {"schema": {}},
    {"schema": "offline-pack@2"}, {"owner_scope_id": "c" * 64},
    {"privacy_class": "public"}, {"data_state": "current"},
    {"source_refresh_performed": True}, {"source_refresh_performed": 0},
    {"plan_fingerprint": None}, {"content_created_at": None}, {"base_pack_id": {}},
])
def test_server_descriptor_tamper_closes_before_object_read(records_factory, changes):
    records = records_factory(*synthetic_archive(), descriptor_changes=changes)
    assert_error(records, "device_ai_archive_metadata_invalid")
    assert len(records.sql) == 1


@pytest.mark.parametrize("changes", [
    {"content_hash": "../../outside"}, {"content_hash": "A" * 64},
    {"byte_count": 0}, {"byte_count": MAX_OBJECT_BYTES + 1}, {"byte_count": 1},
    {"descriptor": []}, {"descriptor": {}},
])
def test_invalid_persisted_row_is_rejected_without_store_access(records_factory, changes):
    records = records_factory(*synthetic_archive(), row_changes=changes)
    assert_error(records, "device_ai_archive_metadata_invalid")


@pytest.mark.parametrize("missing", [False, True])
def test_evidence_object_metadata_missing_or_wrong_size_closes_before_read(records_factory, missing):
    records = records_factory(*synthetic_archive(), object_size=1, include_object=not missing)
    assert_error(records, "device_ai_archive_metadata_invalid")
    assert len(records.sql) == 2
    with records.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.parametrize("failure", [ObjectStoreError("private/path/token=must-not-leak"),
                                    OSError("private/path/token=must-not-leak"),
                                    RuntimeError("private/path/token=must-not-leak")])
def test_object_failures_are_closed_sanitized_errors(records, failure):
    records.store.failure = failure
    error = assert_error(records, "device_ai_archive_object_unavailable", reads=1)
    assert error.__suppress_context__


@pytest.mark.parametrize("bad", [b"same-size", b"", None, bytearray(b"not-immutable")])
def test_observable_store_return_is_independently_verified(records, bad):
    records.store.objects[records.descriptor["sha256"]] = bad
    assert_error(records, "device_ai_archive_object_unavailable", reads=1)


def test_wrong_same_length_bytes_cannot_pass_the_mock_store(records):
    raw = records.raw.replace(b"old-frozen-value", b"new-frozen-value")
    assert len(raw) == len(records.raw)
    records.store.objects[records.descriptor["sha256"]] = raw
    assert_error(records, "device_ai_archive_object_unavailable", reads=1)


@pytest.mark.parametrize("field,value", [
    ("schema", "offline-pack@1"), ("package_id", "wrong"),
    ("owner_scope_id", "c" * 64), ("privacy_class", "restricted"),
    ("data_state", "current"), ("source_refresh_performed", True),
    ("plan_fingerprint", "d" * 64), ("created_at", "other-time"), ("base_pack_id", "other-base"),
])
def test_matching_sha_does_not_hide_frozen_envelope_metadata_tamper(records_factory, field, value):
    raw, descriptor = synthetic_archive()
    envelope = json.loads(raw)
    envelope[field] = value
    changed = json.dumps(envelope, separators=(",", ":")).encode()
    descriptor.update(sha256=hashlib.sha256(changed).hexdigest(), byte_count=len(changed))
    records = records_factory(changed, descriptor)
    assert_error(records, "device_ai_archive_metadata_invalid", reads=1)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"\xef\xbb\xbf{}", b'{"duplicate":1,"duplicate":2}',
                                 b'{"n":1e309}', b'{"n":NaN}', b'{"n":"\xff"}'])
def test_hash_bound_malformed_json_is_a_closed_archive_failure(records_factory, raw):
    _, descriptor = synthetic_archive()
    descriptor.update(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))
    records = records_factory(raw, descriptor)
    assert_error(records, "device_ai_archive_metadata_invalid", reads=1)


@pytest.mark.parametrize("name", list(FIXED_PACKS))
def test_three_original_producer_archives_with_synthetic_owner_fixture(records_factory, monkeypatch, name):
    # Original captures intentionally contain no actor/session ID. Never open
    # producer private.sqlite or recover cookies. This maps a new synthetic row
    # actor to the frozen scope for byte/descriptor/parser coverage only; it does
    # not reproduce or attest the original captured actor relationship.
    raw = (SAMPLES / (name + "-pack.json")).read_bytes()
    descriptor_raw = (SAMPLES / (name + "-descriptor.json")).read_bytes()
    expected_hash, expected_size = FIXED_PACKS[name]
    assert hashlib.sha256(raw).hexdigest() == expected_hash and len(raw) == expected_size
    assert hashlib.sha256(descriptor_raw).hexdigest() == FIXED_DESCRIPTORS[name]
    descriptor = json.loads(descriptor_raw)
    assert descriptor["sha256"] == expected_hash and descriptor["byte_count"] == expected_size
    original_digest = archive.digest

    def synthetic_scope(value):
        assert value == {"namespace": "offline-owner-scope@1", "session": ACTOR}
        return descriptor["owner_scope_id"]

    monkeypatch.setattr(archive, "digest", synthetic_scope)
    records = records_factory(raw, descriptor)
    with Session(records.engine) as db:
        loaded = records.load(db)
    assert loaded.raw_bytes is raw and loaded.binding.sha256 == expected_hash
    assert loaded.binding.byte_count == expected_size
    assert loaded.binding.schema == ("offline-pack@1" if name == "legacy" else "offline-pack@2")
    tire = next(member for member in parse_exact_json(raw)["members"] if member["reference"]["kind"] == "tire")
    assert tire["payload"]["variant"]["facts"]["reference_int"] == NumberLexeme("9007199254740993")
    assert_error(records, "device_ai_archive_not_found", 404, reads=1, actor_session_id="foreign-actor")
    monkeypatch.setattr(archive, "digest", original_digest)
    assert_error(records, "device_ai_archive_metadata_invalid", reads=1)
    assert hashlib.sha256((SAMPLES / (name + "-pack.json")).read_bytes()).hexdigest() == expected_hash
    assert hashlib.sha256((SAMPLES / (name + "-descriptor.json")).read_bytes()).hexdigest() == FIXED_DESCRIPTORS[name]


@pytest.mark.parametrize("case", ["valid", "missing", "corrupt"])
def test_explicit_temporary_file_store_original_bytes_and_failures(records, tmp_path, case):
    store = FileObjectStore(tmp_path / "synthetic-archive-objects")
    if case != "missing":
        assert store.put(records.raw) == records.descriptor["sha256"]
    if case == "corrupt":
        store.path(records.descriptor["sha256"]).write_bytes(b"corrupt")
    with Session(records.engine) as db:
        db.info["object_store"] = store
        arguments = dict(actor_session_id=ACTOR, package_id=records.descriptor["id"],
                         expected_sha256=records.descriptor["sha256"], expected_byte_count=len(records.raw),
                         expected_schema="offline-pack@2", expected_owner_scope_id=records.descriptor["owner_scope_id"])
        if case == "valid":
            assert archive.load_actor_owned_archive(db, **arguments).raw_bytes == records.raw
        else:
            with pytest.raises(archive.ArchiveLoadError) as error:
                archive.load_actor_owned_archive(db, **arguments)
            assert error.value.code == "device_ai_archive_object_unavailable" and error.value.status_code == 503


def test_download_path_is_not_used_as_an_object_locator(records_factory):
    records = records_factory(*synthetic_archive(), descriptor_changes={"download_path": "../../outside?token=unused"})
    with Session(records.engine) as db:
        assert records.load(db).raw_bytes == records.raw
    assert records.store.reads == [(records.descriptor["sha256"], len(records.raw))]


def test_historical_bytes_never_use_new_warehouse_facts_or_new_objects(records):
    warehouse = Table("synthetic_current_facts", MetaData(), Column("value", String, primary_key=True))
    warehouse.create(records.engine)
    new_raw = records.raw.replace(b"old-frozen-value", b"new-current-fact")
    records.store.objects[hashlib.sha256(new_raw).hexdigest()] = new_raw
    with records.engine.begin() as connection:
        connection.execute(warehouse.insert().values(value="current-domain-value"))
    records.sql.clear()
    with Session(records.engine) as db:
        assert records.load(db).raw_bytes == records.raw
    assert len(records.sql) == 2 and all("synthetic_current_facts" not in item[0] for item in records.sql)
    assert records.store.reads == [(records.descriptor["sha256"], len(records.raw))]
    assert set(inspect(records.engine).get_table_names()) == {
        "offline_pack_plans", "offline_packs", "evidence_objects", "synthetic_current_facts"}


def test_loader_reads_persisted_metadata_without_flushing_or_repairing_dirty_instances(records):
    with Session(records.engine) as db:
        row = db.get(OfflinePack, records.descriptor["id"])
        row.content_hash = "d" * 64
        row.descriptor = {"uncommitted": "tamper"}
        db.add(EvidenceObject(raw_hash="e" * 64, byte_count=1))
        records.sql.clear()
        loaded = records.load(db)
        assert loaded.raw_bytes == records.raw and loaded.binding.sha256 == records.descriptor["sha256"]
        assert row.content_hash == "d" * 64 and row.descriptor == {"uncommitted": "tamper"}
        assert row in db.dirty and len(db.new) == 1
        assert len(records.sql) == 2 and all(item[0].lstrip().upper().startswith("SELECT") for item in records.sql)
        db.rollback()


def test_loader_cannot_accept_uploaded_facts_or_client_paths(records):
    with Session(records.engine) as db:
        for forbidden in ("raw_bytes", "facts", "download_url", "object_path", "descriptor"):
            with pytest.raises(TypeError):
                records.load(db, **{forbidden: "client supplied"})
    assert not records.sql and not records.store.reads


def test_fixture_is_an_independent_memory_database_with_only_archive_tables(records):
    with records.engine.connect() as connection:
        databases = connection.exec_driver_sql("PRAGMA database_list").all()
        assert databases[0] == (0, "main", "")
        assert all(name in {"main", "temp"} and filename == "" for _, name, filename in databases)
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    assert set(inspect(records.engine).get_table_names()) == {
        "offline_pack_plans", "offline_packs", "evidence_objects"}


@pytest.mark.parametrize("convert", [float, str])
def test_numerically_equal_expected_size_requires_an_integer(records, convert):
    assert_error(records, "device_ai_archive_expected_mismatch", 409,
                 expected_byte_count=convert(len(records.raw)))


def test_numerically_equal_descriptor_float_size_is_invalid(records_factory):
    raw, descriptor = synthetic_archive()
    records = records_factory(raw, descriptor, descriptor_changes={"byte_count": float(len(raw))})
    assert_error(records, "device_ai_archive_metadata_invalid")


@pytest.mark.parametrize("missing", ["id", "plan_id", "sha256", "byte_count", "schema", "owner_scope_id",
                                     "plan_fingerprint", "content_created_at", "base_pack_id"])
def test_missing_server_descriptor_binding_fields_close(records_factory, missing):
    raw, descriptor = synthetic_archive()
    incomplete = {key: value for key, value in descriptor.items() if key != missing}
    records = records_factory(raw, descriptor, row_changes={"descriptor": incomplete})
    assert_error(records, "device_ai_archive_metadata_invalid")


def test_missing_or_misconfigured_injected_store_is_a_closed_error(records):
    arguments = dict(actor_session_id=ACTOR, package_id=records.descriptor["id"],
                     expected_sha256=records.descriptor["sha256"], expected_byte_count=len(records.raw),
                     expected_schema="offline-pack@2", expected_owner_scope_id=records.descriptor["owner_scope_id"])
    with Session(records.engine) as db:
        for store in (None, "not-a-store"):
            db.info["object_store"] = store
            with pytest.raises(archive.ArchiveLoadError) as failure:
                archive.load_actor_owned_archive(db, **arguments)
            assert failure.value.code == "device_ai_archive_object_unavailable"
        db.info.clear()
        with pytest.raises(archive.ArchiveLoadError) as failure:
            archive.load_actor_owned_archive(db, **arguments)
        assert failure.value.code == "device_ai_archive_object_unavailable"
    assert not records.store.reads


def test_restricted_archive_loading_grants_no_ai_authorization(records_factory):
    raw, descriptor = synthetic_archive()
    raw = raw.replace(b'"privacy_class":"private"', b'"privacy_class":"restricted"')
    descriptor.update(privacy_class="restricted", sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))
    records = records_factory(raw, descriptor)
    with Session(records.engine) as db:
        loaded = records.load(db)
    assert loaded.raw_bytes == raw
    assert set(inspect(records.engine).get_table_names()) == {
        "offline_pack_plans", "offline_packs", "evidence_objects"}
