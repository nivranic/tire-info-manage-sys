"""Owned, SQLite-only internal fact read. No HTTP, acquisition or app startup.

The server supplies a fixed source/grant mapping and the original Bearer header.
Every authorization and evidence check, including pure G2a projection, finishes
inside one fresh BEGIN IMMEDIATE transaction. Database history is not legal proof.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import re
from types import MappingProxyType

from sqlalchemy import func, select

from .db import (AuditEvent, FactVersion, ManualFactRevision, QueryRun, Snapshot,
                 TireVariant, User, VariantLifecycleEvent, Verification, utc)
from .domain import VariantInput, digest, stable_json
from .external_api import TOKEN_PATTERN, _valid_key
from .external_api_models import ApiKey, ApiKeyRevocation
from .external_fact_governance import GovernanceError, GovernanceStore, _reader_preflight
from .external_tire_fact_projection import ProjectionResult, project_observation
from .field_authority import canonical_field, known_values_differ
from .identity_contract import IdentityContractError, _exact_current_binding, schema_version
from .identity_contract_models import VariantIdentityBinding
from .identity_models import IdentityRevision
from .query_owner_models import QueryRunOwnerReceipt
from .query_ownership import QueryOwnershipError, require_query_owner
from .service import business_facts
from .webhook_delivery import valid_seal


_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SOURCE = re.compile(r"[A-Za-z0-9_-]{1,80}")
_HASH = re.compile(r"[0-9a-f]{64}")
_FACTS = frozenset({"utqg_treadwear", "utqg_traction", "utqg_temperature",
                    "eu_fuel_class", "eu_wet_grip", "eu_external_noise_db",
                    "eu_noise_class", "weight_kg", "tread_depth"})
ERROR_CODES = frozenset({
    "reader_backend_unsupported", "reader_schema_required", "reader_clock_invalid",
    "reader_unauthorized", "reader_scope_required", "reader_route_unconfigured",
    "reader_capacity", "reader_policy_invalid", "reader_binding_invalid",
    "reader_identity_invalid", "reader_governance_invalid", "reader_not_available",
    "reader_query_invalid", "reader_cursor_invalid", "reader_cursor_expired",
    "reader_window_changed", "reader_storage_unavailable",
})


class ReaderError(ValueError):
    """Fixed internal codes only; HTTP status normalization is a separate contract."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in ERROR_CODES else "reader_binding_invalid"
        super().__init__(self.code)


def _fail(code):
    raise ReaderError(code)


def _identifier(value, pattern=_ID):
    return type(value) is str and pattern.fullmatch(value) is not None


@dataclass(frozen=True, slots=True, repr=False)
class _Credential:
    key_id: str
    bearer_sha256: str = field(repr=False)
    reader_marker: object = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class ReaderOutcome:
    """Only the immutable G2a result; no ORM, owner or private evidence metadata."""

    _result: ProjectionResult = field(repr=False)

    def to_dict(self):
        return self._result.to_dict()


class OwnedFactReader:
    def __init__(self, engine, routing, registry, *, clock=None):
        if type(routing) is not dict:
            _fail("reader_route_unconfigured")
        if len(routing) > 128:
            _fail("reader_capacity")
        if any(not _identifier(source, _SOURCE) or not _identifier(grant, _SOURCE)
               for source, grant in routing.items()):
            _fail("reader_route_unconfigured")
        self._routing = MappingProxyType(dict(routing))
        self._store = GovernanceStore(engine, clock=clock)
        self._marker = object()
        # Kept as a constructor dependency for server composition. This slice
        # needs no source catalog/authority rank and never calls the registry.

    def capture_credential(self, authorization_headers):
        """Capture, NOT authenticate, request.headers.getlist('authorization')."""
        if type(authorization_headers) not in (list, tuple) or len(authorization_headers) != 1:
            _fail("reader_unauthorized")
        header = authorization_headers[0]
        if type(header) is not str or len(header) != 107 or not header.startswith("Bearer "):
            _fail("reader_unauthorized")
        match = TOKEN_PATTERN.fullmatch(header[7:])
        if match is None:
            _fail("reader_unauthorized")
        hashed = hashlib.sha256(header[7:].encode("ascii")).hexdigest()
        return _Credential(match.group(1), hashed, self._marker)

    def _authenticate(self, db, credential, now, *, budget=None, return_key=False):
        if type(credential) is not _Credential or credential.reader_marker is not self._marker:
            _fail("reader_unauthorized")
        if budget is None:
            _reader_preflight(db, ApiKey, ApiKey.id == credential.key_id, limits={"scopes": 4096})
        elif budget.scalar(db, select(func.json_valid(ApiKey.scopes)).where(ApiKey.id == credential.key_id)) == 0:
            _fail("reader_unauthorized")
        count_statement = select(func.json_array_length(ApiKey.scopes)).where(ApiKey.id == credential.key_id)
        count = db.scalar(count_statement) if budget is None else budget.scalar(db, count_statement)
        if count is not None and (type(count) is not int or count > 3):
            _fail("reader_capacity" if budget is None else "reader_unauthorized")
        key = (db.get(ApiKey, credential.key_id, populate_existing=True) if budget is None else
               budget.get(db, ApiKey, credential.key_id, limits={"scopes": 4096}))
        if budget is None:
            _reader_preflight(db, ApiKeyRevocation, ApiKeyRevocation.key_id == credential.key_id)
        revoked = (db.get(ApiKeyRevocation, credential.key_id, populate_existing=True) if budget is None else
                   budget.get(db, ApiKeyRevocation, credential.key_id))
        try:
            valid = (key is not None and _valid_key(key)
                     and hmac.compare_digest(key.bearer_sha256, credential.bearer_sha256)
                     and utc(key.created_at) <= now < utc(key.expires_at)
                     and (revoked is None or valid_seal(revoked)) and revoked is None
                     and (db.scalar(select(User.id).where(User.id == key.owner_user_id)) if budget is None else
                          next(iter(budget.load(db, User, User.id == key.owner_user_id, columns=("id",))), None))
                     is not None)
        except (ValueError, TypeError, AttributeError, OverflowError):
            valid = False
        if not valid:
            _fail("reader_unauthorized")
        if "facts:read" not in key.scopes:
            _fail("reader_scope_required")
        return key if return_key else key.owner_user_id

    @staticmethod
    def _formal(db, source_id, query_id, verification_id, now, cache, *, budget=None):
        """Validate the exact Q/V/S chain, including genuine success pairing."""
        if not _identifier(query_id) or not _identifier(verification_id):
            _fail("reader_binding_invalid")
        if budget is None:
            _reader_preflight(db, QueryRun, QueryRun.id == query_id,
                          limits={"query": 64 * 1024, "selection_filters": 64 * 1024})
            _reader_preflight(db, Verification, Verification.id == verification_id,
                          limits={"parser_identity": 16 * 1024})
        run = (db.get(QueryRun, query_id, populate_existing=True) if budget is None else
               budget.get(db, QueryRun, query_id, limits={"query": 64 * 1024, "selection_filters": 64 * 1024}))
        verification = (db.get(Verification, verification_id, populate_existing=True) if budget is None else
                        budget.get(db, Verification, verification_id, limits={"parser_identity": 16 * 1024}))
        if (run is None or verification is None or verification.query_id != query_id
                or run.source_id != source_id or verification.source_id != source_id
                or (run.state, verification.status) not in {
                    ("live", "ok"), ("live_verified_304", "not_modified")}
                or type(run.query) is not dict or digest(run.query) != run.query_key
                or verification.query_key != run.query_key):
            _fail("reader_binding_invalid")
        snapshot_id = verification.snapshot_id
        if not _identifier(snapshot_id):
            _fail("reader_binding_invalid")
        if snapshot_id not in cache["snapshots"]:
            sizes = _reader_preflight(db, Snapshot, Snapshot.id == snapshot_id, limits={
                "body": 8 * 1024 * 1024, "parsed_variants": 2 * 1024 * 1024,
                "parser_identity": 16 * 1024}, budget=budget)
            if not sizes:
                _fail("reader_binding_invalid")
            if budget is not None and budget.scalar(db, select(func.json_valid(Snapshot.parsed_variants))
                                                    .where(Snapshot.id == snapshot_id)) != 1:
                _fail("reader_binding_invalid")
            count_statement = select(func.json_array_length(Snapshot.parsed_variants)).where(Snapshot.id == snapshot_id)
            count = db.scalar(count_statement) if budget is None else budget.scalar(db, count_statement)
            if type(count) is not int or count > 256:
                _fail("reader_capacity")
            cache["body_bytes"] += sizes[0]["body"] or 0
            if cache["body_bytes"] > 32 * 1024 * 1024:
                _fail("reader_capacity")
            cache["snapshots"][snapshot_id] = (
                db.get(Snapshot, snapshot_id, populate_existing=True) if budget is None else
                budget.get(db, Snapshot, snapshot_id, limits={"body": 8 * 1024 * 1024,
                    "parsed_variants": 2 * 1024 * 1024, "parser_identity": 16 * 1024}))
        snapshot = cache["snapshots"][snapshot_id]
        if (snapshot.source_id != source_id or snapshot.query_key != run.query_key
                or not _identifier(snapshot.raw_hash, _HASH)
                or type(snapshot.body) is not str or not snapshot.body
                or hashlib.sha256(snapshot.body.encode("utf-8")).hexdigest() != snapshot.raw_hash
                or type(snapshot.source_url) is not str or not snapshot.source_url
                or type(snapshot.parser_version) is not str or not snapshot.parser_version
                or type(snapshot.parsed_variants) is not list
                or verification.parser_identity != snapshot.parser_identity
                or snapshot.parser_identity is not None and type(snapshot.parser_identity) is not dict
                or not utc(run.created_at) <= utc(verification.verified_at) <= now
                or not utc(snapshot.observed_at) <= utc(verification.verified_at)):
            _fail("reader_binding_invalid")
        return run, verification, snapshot

    @staticmethod
    def _owned(db, query_id, owner, *, budget=None):
        # require_query_owner refreshes Q and loads its exact audit. Bound both
        # before allowing that existing helper to materialize their JSON.
        if budget is not None:
            try:
                return require_query_owner(db, query_id, owner, budget=budget)
            except QueryOwnershipError as error:
                _fail("reader_not_available" if error.code == "query_owner_not_found" else "reader_binding_invalid")
        _reader_preflight(db, QueryRun, QueryRun.id == query_id,
                          limits={"query": 64 * 1024, "selection_filters": 64 * 1024})
        _reader_preflight(db, QueryRunOwnerReceipt, QueryRunOwnerReceipt.query_id == query_id)
        receipt = db.get(QueryRunOwnerReceipt, query_id, populate_existing=True)
        if receipt is None:
            _fail("reader_not_available")
        _reader_preflight(db, AuditEvent, AuditEvent.id == receipt.audit_event_id,
                          limits={"detail": 16 * 1024})
        try:
            return require_query_owner(db, query_id, owner)
        except QueryOwnershipError as error:
            _fail("reader_not_available" if error.code == "query_owner_not_found" else "reader_binding_invalid")

    @staticmethod
    def _identity(db, snapshot, variant_id, now):
        if snapshot.identity_contract_version != schema_version():
            _fail("reader_identity_invalid")
        members = [(index, row) for index, row in enumerate(snapshot.parsed_variants)
                   if type(row) is dict and row.get("id") == variant_id]
        if len(members) != 1:
            _fail("reader_binding_invalid")
        index, member = members[0]
        _reader_preflight(db, TireVariant, TireVariant.id == variant_id, limits={"identity": 64 * 1024})
        if db.get(TireVariant, variant_id) is None:
            _fail("reader_identity_invalid")
        _reader_preflight(db, VariantIdentityBinding,
                          VariantIdentityBinding.schema == schema_version(),
                          VariantIdentityBinding.variant_id == variant_id,
                          limits={"current_identity": 64 * 1024, "proof": 64 * 1024})
        binding = _exact_current_binding(db, variant_id)
        parsed = VariantInput.model_validate({key: value for key, value in member.items()
                                             if key in VariantInput.model_fields})
        key, status = parsed.identity_key(snapshot.source_id, snapshot.query_key, index)
        if (key != binding.canonical_key or status != binding.identity_status
                or member.get("identity_key") != key or member.get("identity_status") != status
                or member.get("identity_contract_version") != schema_version()
                or stable_json(parsed.identity()) != stable_json(binding.current_identity)
                or status not in {"complete", "source_scoped"}):
            _fail("reader_identity_invalid")
        _reader_preflight(db, IdentityRevision, IdentityRevision.variant_id == variant_id,
                          maximum=4096, columns={"action"})
        identity = db.execute(select(IdentityRevision.action, IdentityRevision.created_at)
                              .where(IdentityRevision.variant_id == variant_id)
                              .order_by(IdentityRevision.revision.desc()).limit(1)).first()
        if identity is not None and (identity.action != "clear" or utc(identity.created_at) > now):
            _fail("reader_identity_invalid")
        _reader_preflight(db, VariantLifecycleEvent, VariantLifecycleEvent.variant_id == variant_id,
                          maximum=4096, columns={"action", "after_state"})
        lifecycle = db.execute(select(VariantLifecycleEvent.action, VariantLifecycleEvent.after_state,
                                      VariantLifecycleEvent.created_at)
                               .where(VariantLifecycleEvent.variant_id == variant_id)
                               .order_by(VariantLifecycleEvent.revision.desc()).limit(1)).first()
        if lifecycle is not None and (lifecycle.after_state != "active" or lifecycle.action != "restore"
                                      or utc(lifecycle.created_at) > now):
            _fail("reader_governance_invalid")
        return member, {"variant_id": variant_id, "contract_version": schema_version(),
                        "status": status, "values": binding.current_identity}

    @staticmethod
    def _fact(db, snapshot, member, variant_id, now):
        where = (FactVersion.variant_id == variant_id, FactVersion.source_id == snapshot.source_id)
        _reader_preflight(db, FactVersion, *where, maximum=4096, limits={"facts": 64 * 1024})
        facts = member.get("facts")
        if type(facts) is not dict:
            _fail("reader_binding_invalid")
        expected_hash = digest(business_facts(facts))
        statement = select(FactVersion).where(*where, FactVersion.facts_hash == expected_hash)
        if "fact_version" in member:
            version = member["fact_version"]
            if type(version) is not int or version < 1:
                _fail("reader_binding_invalid")
            statement = statement.where(FactVersion.version == version)
        else:
            statement = statement.where(FactVersion.observed_at <= snapshot.observed_at)
        fact = db.scalar(statement.order_by(FactVersion.version.desc()).limit(1))
        if (fact is None or digest(fact.facts) != fact.facts_hash
                or utc(fact.observed_at) > now or utc(fact.observed_at) > utc(snapshot.observed_at)):
            _fail("reader_governance_invalid")
        # Only this id participates in stale-manual detection; its current facts
        # are never substituted into the selected observation.
        current_id = db.scalar(select(FactVersion.id).where(*where)
                               .order_by(FactVersion.version.desc()).limit(1))
        return facts, current_id

    @staticmethod
    def _suppressed(db, variant_id, source_id, current_id, now):
        _reader_preflight(db, ManualFactRevision, ManualFactRevision.variant_id == variant_id,
                          ManualFactRevision.source_id == source_id, maximum=4096,
                          columns={"field", "action", "base_fact_id"})
        rows = db.execute(select(ManualFactRevision.field, ManualFactRevision.action,
                                 ManualFactRevision.base_fact_id, ManualFactRevision.created_at)
                          .where(ManualFactRevision.variant_id == variant_id,
                                 ManualFactRevision.source_id == source_id)
                          .order_by(ManualFactRevision.revision.desc()).limit(4096))
        latest, suppressed = set(), set()
        for row in rows:
            if row.field in latest:
                continue
            latest.add(row.field)
            if row.action not in {"clear_override", "manual_override", "revoke"} or utc(row.created_at) > now:
                _fail("reader_governance_invalid")
            field = canonical_field(row.field)
            status = ("cleared" if row.action == "clear_override" else "needs_review"
                      if row.base_fact_id != current_id else "revoked"
                      if row.action == "revoke" else "manual_override")
            # clear wins only for this raw name. Never remove another alias's
            # suppression, including stale-base needs_review.
            if status != "cleared" and field in _FACTS:
                suppressed.add(field)
        return suppressed

    @staticmethod
    def _project(policy, observation, identity, facts, suppressed, now, *, budget=None, allow_empty=False):
        groups, conflicts, count = {}, set(), 0

        def value(field, raw):
            nonlocal count
            count += 1
            if count > 64:
                _fail("reader_capacity")
            if budget is not None:
                budget.projection()
            payload = {"observation": observation, "identity": identity,
                       "facts": {field: raw}, "conflicted_fields": []}
            if budget is not None:
                budget.json(payload)
            result = project_observation(policy, payload, now=now)
            if budget is not None:
                budget.json(result.to_dict())
            if result.status == "invalid":
                _fail("reader_capacity" if result.reason == "projection_capacity" else
                      "reader_policy_invalid" if result.reason == "policy_invalid" else "reader_binding_invalid")
            groups.setdefault(field, []).append(raw)

        for raw_field, raw in facts.items():
            field = canonical_field(raw_field)
            if field in _FACTS:
                value(field, raw)
        explicit = facts.get("source_field_conflicts", [])
        if type(explicit) is not list:
            _fail("reader_binding_invalid")
        for conflict in explicit:
            if type(conflict) is not dict or type(conflict.get("field")) is not str:
                _fail("reader_binding_invalid")
            field = canonical_field(conflict["field"].removeprefix("facts.").removeprefix("identity."))
            if field not in _FACTS:
                continue
            conflicts.add(field)
            values = conflict.get("values")
            if type(values) is not list:
                _fail("reader_binding_invalid")
            for item in values:
                if type(item) is not dict or "value" not in item:
                    _fail("reader_binding_invalid")
                value(field, item["value"])
        projected = {}
        for field, values in groups.items():
            if known_values_differ(values):
                conflicts.add(field)
            else:
                projected[field] = next((item for item in values if item is not None), None)
        projected = {key: value for key, value in projected.items() if key not in suppressed}
        conflicts.difference_update(suppressed)
        if budget is not None:
            budget.projection(final=True)
        payload = {"observation": observation, "identity": identity,
                   "facts": projected, "conflicted_fields": sorted(conflicts)}
        if budget is not None:
            budget.json(payload)
        result = project_observation(policy, payload, now=now)
        if budget is not None:
            budget.json(result.to_dict())
        if result.status == "invalid":
            _fail("reader_capacity" if result.reason == "projection_capacity" else
                  "reader_policy_invalid" if result.reason == "policy_invalid" else "reader_binding_invalid")
        if result.status != "projected":
            if allow_empty and result.status == "not_applicable" and result.reason == "no_permitted_facts":
                return ReaderOutcome(result)
            _fail("reader_not_available")
        return ReaderOutcome(result)

    def read_page(self, credential, *, query_pairs):
        from .external_fact_page import read_page
        return read_page(self, credential, query_pairs=query_pairs)

    def read_one(self, credential, *, source_id, query_id, verification_id, variant_id):
        try:
            if not _identifier(source_id, _SOURCE) or not all(_identifier(item) for item in
                                                            (query_id, verification_id, variant_id)):
                _fail("reader_not_available")
            grant = self._routing.get(source_id)
            if grant is None:
                _fail("reader_route_unconfigured")
            with self._store._reader_transaction() as (db, now):
                owner = self._authenticate(db, credential, now)
                rows, current = self._store._reader_load(db, grant)
                if current.policy is None or current.state != "approved":
                    _fail("reader_not_available")
                if current.policy.latest.source_id != source_id:
                    _fail("reader_policy_invalid")
                cache = {"snapshots": {}, "body_bytes": 0}
                for binding in rows[-1].binding_receipts:
                    run, verification, snapshot = self._formal(db, source_id, binding["query_id"],
                                                               binding["verification_id"], now, cache)
                    if (snapshot.id != binding["snapshot_id"] or snapshot.raw_hash != binding["raw_hash"]
                            or snapshot.parser_version != binding["parser_version"]
                            or run.query_key != binding["query_key"]
                            or (digest(snapshot.parser_identity) if snapshot.parser_identity is not None else None)
                            != binding["parser_identity_digest"]):
                        _fail("reader_binding_invalid")
                receipt = self._owned(db, query_id, owner)
                if utc(receipt.captured_at) > now:
                    _fail("reader_binding_invalid")
                _, verification, snapshot = self._formal(db, source_id, query_id, verification_id, now, cache)
                member, identity = self._identity(db, snapshot, variant_id, now)
                facts, current_id = self._fact(db, snapshot, member, variant_id, now)
                suppressed = self._suppressed(db, variant_id, source_id, current_id, now)
                observation = {"source_id": source_id, "snapshot_id": snapshot.id,
                               "raw_hash": snapshot.raw_hash, "parser_version": snapshot.parser_version}
                outcome = self._project(current.policy, observation, identity, facts, suppressed, now)
            return outcome
        except ReaderError:
            raise
        except GovernanceError as error:
            raise ReaderError(error.code if error.code in ERROR_CODES else "reader_policy_invalid") from None
        except IdentityContractError:
            raise ReaderError("reader_identity_invalid") from None
        except Exception:
            raise ReaderError("reader_binding_invalid") from None
