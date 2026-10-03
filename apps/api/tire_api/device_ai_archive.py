"""Internal actor-owned frozen archive loading, without AI authorization.

The actor must come from the server session (eventually request.state), never a
client body. Expected client metadata only detects a changed selection; it is
not an ownership credential. No uploaded facts, URL or object path is accepted.

This proves ownership of an immutable server export and its byte integrity.
Current visibility, source rights, identity/revocation, Host selection consent
and independent Provider consent remain mandatory future caller gates. Loading
an archive does not create a preparation or grant permission to use it for AI.
No routes, startup registration, warehouse reads or content repair occur here.
"""
from dataclasses import dataclass, field
import re
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import EvidenceObject
from .device_ai_projection import FrozenPackBinding, ProjectionError, parse_exact_json
from .domain import digest
from .object_store import MAX_OBJECT_BYTES, checked
from .offline_models import OfflinePack


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMAS = {"offline-pack-descriptor@1": "offline-pack@1",
            "offline-pack-descriptor@2": "offline-pack@2"}


class ArchiveObjectStore(Protocol):
    def get(self, digest: str, size: int) -> bytes: ...


class ArchiveLoadError(ValueError):
    """Closed internal error mapping; no object path, source body or actor data."""

    def __init__(self, code: str, status_code: int):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OwnedArchive:
    binding: FrozenPackBinding
    raw_bytes: bytes = field(repr=False)


def _require(condition: bool, code: str = "device_ai_archive_metadata_invalid",
             status_code: int = 503) -> None:
    if not condition:
        raise ArchiveLoadError(code, status_code)


def _identifier(value: object) -> bool:
    return (type(value) is str and 0 < len(value) <= 64
            and value == value.strip() and value.isprintable())


def _hash(value: object) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def _size(value: object) -> bool:
    return type(value) is int and 0 < value <= MAX_OBJECT_BYTES


def load_actor_owned_archive(db: Session, *, actor_session_id: str, package_id: str,
                             expected_sha256: str, expected_byte_count: int,
                             expected_schema: str, expected_owner_scope_id: str) -> OwnedArchive:
    """Read only the actor's archived original, using keyword metadata scalars.

    The caller supplies a Session with an explicitly selected object_store in
    db.info. No configured store or environment is discovered. Reads suppress
    autoflush and select persisted columns, avoiding mutable ORM identity-map
    values. The caller must enforce current authorization before later AI use.
    """
    not_found = "device_ai_archive_not_found"
    _require(_identifier(actor_session_id) and _identifier(package_id), not_found, 404)
    with db.no_autoflush:
        # Ownership precedes all descriptor/expected/EvidenceObject/store access.
        row = db.execute(select(OfflinePack.id, OfflinePack.plan_id,
                                OfflinePack.content_hash, OfflinePack.byte_count,
                                OfflinePack.descriptor).where(
            OfflinePack.id == package_id,
            OfflinePack.actor_session_id == actor_session_id)).one_or_none()
        _require(row is not None, not_found, 404)
        descriptor = row.descriptor
        _require(type(descriptor) is dict and _identifier(row.id)
                 and _identifier(row.plan_id) and _hash(row.content_hash) and _size(row.byte_count))
        descriptor_schema = descriptor.get("schema")
        _require(type(descriptor_schema) is str and descriptor_schema in _SCHEMAS)
        schema = _SCHEMAS[descriptor_schema]
        owner_scope = digest({"namespace": "offline-owner-scope@1", "session": actor_session_id})
        _require(descriptor.get("id") == row.id and descriptor.get("plan_id") == row.plan_id
                 and descriptor.get("sha256") == row.content_hash
                 and _size(descriptor.get("byte_count")) and descriptor["byte_count"] == row.byte_count
                 and descriptor.get("owner_scope_id") == owner_scope
                 and descriptor.get("privacy_class") in ("private", "restricted")
                 and descriptor.get("data_state") == "local_snapshot"
                 and descriptor.get("source_refresh_performed") is False
                 and _hash(descriptor.get("plan_fingerprint"))
                 and type(descriptor.get("content_created_at")) is str
                 and bool(descriptor["content_created_at"])
                 and "base_pack_id" in descriptor
                 and (descriptor["base_pack_id"] is None or _identifier(descriptor["base_pack_id"])))
        _require(_hash(expected_sha256) and _size(expected_byte_count)
                 and type(expected_schema) is str and type(expected_owner_scope_id) is str
                 and expected_sha256 == row.content_hash and expected_byte_count == row.byte_count
                 and expected_schema == schema and expected_owner_scope_id == owner_scope,
                 "device_ai_archive_expected_mismatch", 409)
        stored = db.execute(select(EvidenceObject.raw_hash, EvidenceObject.byte_count).where(
            EvidenceObject.raw_hash == row.content_hash)).one_or_none()
        _require(stored is not None and stored.raw_hash == row.content_hash
                 and _size(stored.byte_count) and stored.byte_count == row.byte_count)

    # Only the server row's validated content address reaches the injected store.
    try:
        store: ArchiveObjectStore = db.info["object_store"]
        raw = store.get(row.content_hash, row.byte_count)
        _require(type(raw) is bytes, "device_ai_archive_object_unavailable")
        checked(raw, row.content_hash, row.byte_count)  # Also verify observable/mock stores.
    except Exception:
        # A store implementation/configuration failure must not expose its
        # filesystem, provider details or credentials through this boundary.
        raise ArchiveLoadError("device_ai_archive_object_unavailable", 503) from None

    try:
        envelope = parse_exact_json(raw)
    except ProjectionError:
        raise ArchiveLoadError("device_ai_archive_metadata_invalid", 503) from None
    _require(type(envelope) is dict and envelope.get("schema") == schema
             and envelope.get("package_id") == row.id
             and envelope.get("owner_scope_id") == owner_scope
             and envelope.get("privacy_class") == descriptor["privacy_class"]
             and envelope.get("data_state") == "local_snapshot"
             and envelope.get("source_refresh_performed") is False
             and envelope.get("plan_fingerprint") == descriptor["plan_fingerprint"]
             and envelope.get("created_at") == descriptor["content_created_at"]
             and "base_pack_id" in envelope and envelope["base_pack_id"] == descriptor["base_pack_id"])
    return OwnedArchive(FrozenPackBinding(row.id, owner_scope, row.content_hash,
                                          row.byte_count, schema), raw)
