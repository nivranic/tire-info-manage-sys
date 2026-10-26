"""Controlled local license ledger. No HTTP, collection, Provider or app startup.

The database and authenticated workstation operator are the authority boundary.
Hashes detect inconsistent records; they do not establish genuine legal rights.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import JSON, LargeBinary, String, Text, cast, func, select, text
from sqlalchemy.orm import Session

from .auth import verify_password
from .db import AuditEvent, QueryRun, Snapshot, User, Verification, uid, utc
from .external_fact_models import ExternalFactGrantRevision as Revision, ExternalFactLicenseEvidence as Evidence, MAX_EVIDENCE_BYTES, VERSION
from .external_fact_policy import PolicyValidationError, evaluate_applicability, validate_revision_chain

_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_HASH = re.compile(r"[0-9a-f]{64}")
_STATE = {"approve": "approved", "restrict": "restricted", "withdraw": "withdrawn"}
_EVENT_FIELDS = (
    "id", "grant_id", "source_id", "revision", "record_digest", "previous_digest",
    "evidence_sha256", "license_reference", "binding_receipts", "action", "actor_user_id",
    "actor_username_snapshot", "reason", "expected_revision", "expected_head", "preview_fingerprint",
    "idempotency_key", "request_hash", "audit_event_id",
)


class GovernanceError(ValueError):
    """Fixed codes only; never echo secrets, paths, bodies or SQL exceptions."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise GovernanceError(code)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _stamp(value):
    return utc(value).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(value, limit):
    if type(value) is not str or not 1 <= len(value) <= limit or value != value.strip() or not value.isprintable():
        _fail("request_invalid")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        _fail("request_invalid")
    return value


def _closed(value, keys):
    if type(value) is not dict or any(type(key) is not str for key in value) or value.keys() != keys:
        _fail("request_invalid")


def _identifier(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("request_invalid")
    return value


def _terms(body):
    if type(body) is not bytes or not 1 <= len(body) <= MAX_EVIDENCE_BYTES:
        _fail("evidence_invalid")
    try:
        value = body.decode("utf-8", errors="strict")
    except UnicodeError:
        _fail("evidence_invalid")
    if "\x00" in value:
        _fail("evidence_invalid")
    return hashlib.sha256(body).hexdigest()


def _reference(value):
    _plain(value, 2048)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in value or "#" in value or "\\" in value
                or parsed.port not in (None, 443) or parsed.netloc not in (host, host + ":443")
                or host.endswith((".local", ".localhost", ".internal"))
                or re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host) is None):
            _fail("request_invalid")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            _fail("request_invalid")
        value.encode("ascii", errors="strict")
    except (ValueError, UnicodeError):
        _fail("request_invalid")
    return value


def _seal(record):
    return {**record, "digest": _digest(record)}


def _event_digest(row):
    return _digest({key: getattr(row, key) for key in _EVENT_FIELDS} | {"created_at": _stamp(row.created_at)})


def _audit_detail(row):
    return {"event_id": row.id, "grant_id": row.grant_id, "revision": row.revision,
            "action": row.action, "actor_user_id": row.actor_user_id,
            "idempotency_key": row.idempotency_key, "record_digest": row.record_digest,
            "event_digest": row.event_digest}


def _reader_preflight(db, model, *where, maximum=1, limits=None, columns=None, budget=None):
    """Read lengths/counts, never JSON/text payloads, before reader materialization.

    Limits are UTF-8 storage bytes on SQLite. The extra row detects overflow;
    this is an engineering allocation bound, not process memory isolation.
    """
    if budget is not None:
        return budget.preflight(db, model, *where, maximum=maximum, limits=limits, columns=columns)
    limits = limits or {}
    selected = [column for column in model.__table__.columns
                if (columns is None or column.key in columns)
                and isinstance(column.type, (String, JSON, LargeBinary))]
    expressions = [func.length(cast(cast(column, Text), LargeBinary)).label(column.key)
                   for column in selected]
    rows = list(db.execute(select(*expressions, text("1 AS _present"))
                           .select_from(model).where(*where).limit(maximum + 1)).mappings())
    if len(rows) > maximum:
        _fail("reader_capacity")
    for row in rows:
        for column in selected:
            default = (column.type.length * 4 if isinstance(column.type, String)
                       and column.type.length else 64 * 1024)
            length = row[column.key]
            if length is not None and (type(length) is not int or length > limits.get(column.key, default)):
                _fail("reader_capacity")
    return rows


class _ReaderSession(Session):
    """Internal read-only session; a hidden helper must not flush/commit writes."""

    def flush(self, objects=None):
        if self.new or self.dirty or self.deleted:
            _fail("reader_governance_invalid")

    def commit(self):
        _fail("reader_governance_invalid")

    def rollback(self):
        _fail("reader_governance_invalid")

    @staticmethod
    def _select_only(statement):
        if not getattr(statement, "is_select", False):
            _fail("reader_governance_invalid")

    def execute(self, statement, *args, **kwargs):
        self._select_only(statement)
        return super().execute(statement, *args, **kwargs)

    def scalar(self, statement, *args, **kwargs):
        self._select_only(statement)
        return super().scalar(statement, *args, **kwargs)

    def scalars(self, statement, *args, **kwargs):
        self._select_only(statement)
        return super().scalars(statement, *args, **kwargs)


@dataclass(frozen=True, slots=True, repr=False)
class _AuthenticatedActor:
    user_id: str
    credential: str = field(repr=False)
    store_marker: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class CurrentPolicy:
    grant_id: str
    revision: int
    head: str | None
    state: str
    policy: object = field(repr=False)

    def summary(self, *, now):
        if self.policy is None:
            status, reason = "not_applicable", "grant_missing"
        else:
            latest = self.policy.latest
            observation = latest.coverage.observations[0]
            decision = evaluate_applicability(self.policy,
                {"source_id": latest.source_id, "snapshot_id": observation.snapshot_id,
                 "raw_hash": observation.raw_hash, "parser_version": observation.parser_version},
                list(latest.coverage.field_keys), now=now)
            status, reason = decision.status, decision.reason
        return {"grant_id": self.grant_id, "revision": self.revision, "head": self.head, "state": self.state,
                "applicability": status, "applicability_reason": reason}


class GovernanceStore:
    def __init__(self, engine, *, clock=None):
        self.engine = engine
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._auth_marker = object()

    def _now(self):
        value = self.clock()
        if type(value) is not datetime or value.tzinfo is not timezone.utc:
            _fail("clock_invalid")
        return value.replace(microsecond=0)

    def authenticate(self, username, password):
        if type(username) is not str or re.fullmatch(r"[A-Za-z0-9_-]{3,32}", username) is None:
            _fail("admin_authentication_required")
        if type(password) is not str or not 8 <= len(password) <= 200:
            _fail("admin_authentication_required")
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.username == username))
            if (user is None or not user.is_admin or type(user.password_hash) is not str
                    or len(user.password_hash) > 256 or not verify_password(password, user.password_hash)):
                _fail("admin_authentication_required")
            return _AuthenticatedActor(user.id, user.password_hash, self._auth_marker)

    def _actor(self, db, actor):
        if type(actor) is not _AuthenticatedActor or actor.store_marker is not self._auth_marker:
            _fail("admin_authentication_required")
        user = db.get(User, actor.user_id, populate_existing=True, with_for_update=True)
        if user is None or not user.is_admin or user.password_hash != actor.credential:
            _fail("admin_authorization_changed")
        return user

    @contextmanager
    def _transaction(self, *, require_schema=True):
        with self.engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            elif connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(821741905)")
            else:
                _fail("backend_unsupported")
            db = Session(bind=connection, expire_on_commit=False)
            try:
                if require_schema and VERSION not in set(connection.execute(text("SELECT version FROM tire_schema_versions")).scalars()):
                    _fail("schema_required")
                yield db
                db.flush()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                db.close()

    def _load(self, db, grant_id, *, budget=None):
        rows = (list(db.scalars(select(Revision).where(Revision.grant_id == grant_id)
                               .order_by(Revision.revision).limit(257))) if budget is None else
                budget.load(db, Revision, Revision.grant_id == grant_id, maximum=256,
                            order=(Revision.revision,),
                            limits={"record": 128 * 1024, "binding_receipts": 128 * 1024}))
        if not rows:
            return rows, CurrentPolicy(grant_id, 0, None, "missing", None)
        try:
            if len(rows) > 256:
                _fail("ledger_invalid")
            audit_where = AuditEvent.id.in_([row.audit_event_id for row in rows])
            audits = {row.id: row for row in (
                db.scalars(select(AuditEvent).where(audit_where)) if budget is None else
                budget.load(db, AuditEvent, audit_where, maximum=256, limits={"detail": 16 * 1024}))}
            records = []
            size = 0
            previous = None
            for row in rows:
                if budget is not None:
                    budget.json(row.record)
                    budget.json(row.binding_receipts)
                size += len(_json(row.record).encode("utf-8"))
                if size > 32 * 1024 * 1024 or len(_json(row.record).encode("utf-8")) > 128 * 1024:
                    _fail("ledger_invalid")
                if (row.action not in _STATE or row.record["state"] != _STATE[row.action]
                        or row.record["grant_id"] != row.grant_id or row.record["source_id"] != row.source_id
                        or row.record["revision"] != row.revision or row.record["digest"] != row.record_digest
                        or row.record["previous_digest"] != row.previous_digest
                        or row.expected_revision != row.revision - 1 or row.expected_head != row.previous_digest
                        or row.record["review"]["reviewer"] != row.actor_user_id
                        or row.record["review"]["reviewed_at"] != _stamp(row.created_at)
                        or row.record["rights"]["evidence_sha256"] != row.evidence_sha256
                        or row.record["rights"]["evidence_reference"] != "external-fact-license-evidence:sha256:" + row.evidence_sha256
                        or row.event_digest != _event_digest(row)
                        or (row.revision == 1 and row.action == "withdraw")
                        or (row.revision == 256 and row.action != "withdraw")
                        or (previous is not None and previous.record["state"] == "withdrawn")):
                    _fail("ledger_invalid")
                if previous is not None and row.action in ("restrict", "withdraw"):
                    if (any(row.record[key] != previous.record[key] for key in ("coverage", "rights", "validity"))
                            or row.binding_receipts != previous.binding_receipts
                            or row.license_reference != previous.license_reference):
                        _fail("ledger_invalid")
                if str(UUID(row.idempotency_key)) != row.idempotency_key:
                    _fail("ledger_invalid")
                observations = row.record["coverage"]["observations"]
                if type(row.binding_receipts) is not list or len(row.binding_receipts) != len(observations):
                    _fail("ledger_invalid")
                for item, binding in zip(observations, row.binding_receipts):
                    if (type(binding) is not dict
                            or binding.keys() != {"snapshot_id", "raw_hash", "parser_version", "source_id",
                                                  "verification_id", "query_id", "query_key", "parser_identity_digest"}
                            or any(binding[key] != item[key] for key in item)
                            or binding["source_id"] != row.source_id
                            or any(type(binding[key]) is not str or not binding[key] or len(binding[key]) > 64
                                   for key in ("verification_id", "query_id"))
                            or type(binding["query_key"]) is not str or _HASH.fullmatch(binding["query_key"]) is None
                            or (binding["parser_identity_digest"] is not None and
                                (type(binding["parser_identity_digest"]) is not str
                                 or _HASH.fullmatch(binding["parser_identity_digest"]) is None))):
                        _fail("ledger_invalid")
                audit = audits.get(row.audit_event_id)
                if (audit is None or audit.action != "external_fact_policy_changed"
                        or audit.query_id is not None or audit.consent_id is not None
                        or audit.session_id != "fact_cli:" + UUID(row.idempotency_key).hex
                        or audit.detail != _audit_detail(row) or _stamp(audit.created_at) != _stamp(row.created_at)):
                    _fail("ledger_invalid")
                records.append(row.record)
                previous = row
            if budget is not None:
                budget.json(records)
            policy = validate_revision_chain(records, expected_head=rows[-1].record_digest)
            evidence = (db.get(Evidence, rows[-1].evidence_sha256) if budget is None else
                        budget.get(db, Evidence, rows[-1].evidence_sha256,
                                   limits={"body": MAX_EVIDENCE_BYTES}))
            if evidence is None or evidence.byte_count != len(evidence.body) or _terms(evidence.body) != evidence.raw_hash:
                _fail("ledger_invalid")
            return rows, CurrentPolicy(grant_id, rows[-1].revision, rows[-1].record_digest, rows[-1].record["state"], policy)
        except (PolicyValidationError, KeyError, TypeError, ValueError, AttributeError, OverflowError):
            _fail("ledger_invalid")

    @contextmanager
    def _reader_transaction(self, *, budget=None):
        """SQLite-only owned read; keep authorization/projection under one lock.

        Unlike management transactions, this never flushes/commits the Session
        and keeps clock microseconds. Only the clean owned boundary may commit.
        """
        if self.engine.dialect.name != "sqlite":
            _fail("reader_backend_unsupported")
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            owned_transaction = connection.get_transaction()
            db = _ReaderSession(bind=connection, autoflush=False, expire_on_commit=False)
            try:
                required = {VERSION, "026_query_ownership"}
                try:
                    found = (set(connection.execute(text(
                        "SELECT version FROM tire_schema_versions WHERE version IN "
                        "('025_external_fact_governance','026_query_ownership')")).scalars())
                        if budget is None else budget.schema(connection))
                except Exception as error:
                    if budget is not None:
                        from .external_fact_page_budget import PageCapacityError
                        if isinstance(error, PageCapacityError):
                            raise
                    _fail("reader_schema_required")
                if found != required:
                    _fail("reader_schema_required")
                try:
                    now = self.clock()
                except Exception:
                    _fail("reader_clock_invalid")
                if type(now) is not datetime or now.tzinfo is not timezone.utc:
                    _fail("reader_clock_invalid")
                yield db, now
                if (db.new or db.dirty or db.deleted or connection.get_transaction() is not owned_transaction
                        or not owned_transaction.is_active):
                    _fail("reader_governance_invalid")
                connection.commit()
            finally:
                db.close()
                connection.rollback()

    def _reader_load(self, db, grant_id, *, budget=None):
        """Bound the existing trusted loader before it decodes ledger payloads."""
        rows = _reader_preflight(db, Revision, Revision.grant_id == grant_id, maximum=256,
                                 limits={"record": 128 * 1024, "binding_receipts": 128 * 1024}, budget=budget)
        if sum(row["record"] or 0 for row in rows) > 32 * 1024 * 1024:
            _fail("reader_capacity")
        if budget is not None:
            validity = budget.load(db, Revision, Revision.grant_id == grant_id, maximum=256,
                                   columns=("id",), order=(Revision.revision,),
                                   extra=(func.json_valid(Revision.binding_receipts),))
            if any(row[1] != 1 for row in validity):
                _fail("reader_policy_invalid")
        anchors = (list(db.execute(select(Revision.audit_event_id, Revision.evidence_sha256,
                                         func.json_array_length(Revision.binding_receipts))
                                  .where(Revision.grant_id == grant_id)
                                  .order_by(Revision.revision).limit(257))) if budget is None else
                   budget.load(db, Revision, Revision.grant_id == grant_id, maximum=256,
                               columns=("audit_event_id", "evidence_sha256"), order=(Revision.revision,),
                               extra=(func.json_array_length(Revision.binding_receipts),)))
        if any(type(row[2]) is not int or not 0 <= row[2] <= 256 for row in anchors):
            _fail("reader_capacity")
        if anchors:
            _reader_preflight(db, AuditEvent, AuditEvent.id.in_([row[0] for row in anchors]),
                              maximum=256, limits={"detail": 16 * 1024}, budget=budget)
            _reader_preflight(db, Evidence, Evidence.raw_hash == anchors[-1][1],
                              limits={"body": MAX_EVIDENCE_BYTES}, budget=budget)
        return self._load(db, grant_id, budget=budget)

    @contextmanager
    def current_policy_transaction(self, grant_id):
        """Own a fresh transaction/lock; accepts no client head or record chain.

        Future fact projection must finish inside this context, not retain policy
        across requests. An applicable policy still does not validate fact values.
        """
        _identifier(grant_id)
        with self._transaction() as db:
            _, current = self._load(db, grant_id)
            yield current

    def current(self, actor, grant_id):
        _identifier(grant_id)
        with self._transaction() as db:
            self._actor(db, actor)
            return self._load(db, grant_id)[1].summary(now=self._now())

    def _bindings(self, db, source_id, coverage):
        result, total = [], 0
        for item in coverage["observations"]:
            snapshot = db.get(Snapshot, item["snapshot_id"])
            if (snapshot is None or snapshot.source_id != source_id or snapshot.raw_hash != item["raw_hash"]
                    or snapshot.parser_version != item["parser_version"] or type(snapshot.body) is not str
                    or not snapshot.body or len(snapshot.body) > 32 * 1024 * 1024 - total):
                _fail("observation_binding_invalid")
            body = snapshot.body.encode("utf-8", errors="strict")
            total += len(body)
            if total > 32 * 1024 * 1024:
                _fail("binding_capacity")
            if hashlib.sha256(body).hexdigest() != snapshot.raw_hash:
                _fail("observation_binding_invalid")
            selected = db.execute(select(Verification, QueryRun).join(QueryRun, QueryRun.id == Verification.query_id)
                .where(Verification.snapshot_id == snapshot.id, Verification.source_id == source_id,
                       Verification.query_key == snapshot.query_key, Verification.status.in_(("ok", "not_modified")),
                       QueryRun.source_id == source_id, QueryRun.query_key == snapshot.query_key)
                .order_by(Verification.verified_at.desc(), Verification.id.desc()).limit(1)).first()
            if (selected is None or _digest(selected[1].query) != snapshot.query_key
                    or selected[0].parser_identity != snapshot.parser_identity):
                _fail("observation_binding_invalid")
            result.append({**item, "source_id": source_id, "verification_id": selected[0].id,
                           "query_id": selected[1].id, "query_key": snapshot.query_key,
                           "parser_identity_digest": _digest(snapshot.parser_identity) if snapshot.parser_identity is not None else None})
        return result

    def _prepare(self, db, actor, request, terms, current, rows, now):
        base_keys = {"schema", "action", "grant_id", "reason"}
        full = type(request) is dict and (request.get("action") == "approve" or current.revision == 0)
        keys = base_keys | ({"source_id", "coverage", "rights", "validity", "license_reference", "rights_reviewed"} if full else set())
        _closed(request, keys)
        if (request["schema"] != "external-fact-governance-request@1"
                or type(request["action"]) is not str or request["action"] not in _STATE):
            _fail("request_invalid")
        grant_id = _identifier(request["grant_id"])
        reason = _plain(request["reason"], 1000)
        action = request["action"]
        if grant_id != current.grant_id:
            _fail("request_invalid")
        if current.state == "withdrawn":
            _fail("grant_withdrawn")
        if action == "withdraw" and current.revision == 0:
            _fail("grant_not_found")
        if current.revision >= (256 if action == "withdraw" else 255):
            _fail("revision_capacity")
        user = self._actor(db, actor)
        if full:
            _closed(request["rights"], {"holder", "basis"})
            if request["rights_reviewed"] is not True:
                _fail("rights_review_required")
            source = _identifier(request["source_id"])
            if rows and source != rows[-1].source_id:
                _fail("source_changed")
            evidence_hash = _terms(terms)
            reference = _reference(request["license_reference"])
            record = {"schema": "external-fact-policy@1", "purpose": "external_structured_fact_read",
                      "grant_id": grant_id, "source_id": source, "revision": 1, "previous_digest": None,
                      "state": _STATE[action], "coverage": request["coverage"],
                      "rights": {**request["rights"], "evidence_reference": "external-fact-license-evidence:sha256:" + evidence_hash,
                                 "evidence_sha256": evidence_hash},
                      "review": {"reviewer": user.id, "reviewed_at": _stamp(now)}, "validity": request["validity"]}
            try:
                initial = _seal(record)
                policy = validate_revision_chain([initial], expected_head=initial["digest"])
            except (PolicyValidationError, TypeError, ValueError, UnicodeError, RecursionError):
                _fail("request_invalid")
            bindings = self._bindings(db, source, request["coverage"])
            if action == "approve":
                observation = {"source_id": source, **record["coverage"]["observations"][0]}
                if evaluate_applicability(policy, observation, record["coverage"]["field_keys"], now=now).status != "applicable":
                    _fail("approval_not_effective")
        else:
            if terms is not None:
                _fail("request_invalid")
            record = json.loads(_json(rows[-1].record))
            record.pop("digest")
            record["state"] = _STATE[action]
            record["review"] = {"reviewer": user.id, "reviewed_at": _stamp(now)}
            evidence_hash = rows[-1].evidence_sha256
            reference = rows[-1].license_reference
            bindings = json.loads(_json(rows[-1].binding_receipts))
            if current.state == record["state"]:
                _fail("no_changes")
        record["revision"] = current.revision + 1
        record["previous_digest"] = current.head
        if rows and all(record[key] == rows[-1].record[key] for key in
                        ("state", "coverage", "rights", "validity")) and (
                reference == rows[-1].license_reference and bindings == rows[-1].binding_receipts
                and reason == rows[-1].reason):
            _fail("no_changes")
        record = _seal(record)
        try:
            validate_revision_chain([row.record for row in rows] + [record], expected_head=record["digest"])
        except PolicyValidationError:
            _fail("request_invalid")
        if len(_json(record).encode("utf-8")) > 128 * 1024:
            _fail("record_capacity")
        normalized = json.loads(_json(request))
        fingerprint = _digest({"request": normalized, "actor_user_id": user.id,
                               "revision": current.revision, "head": current.head,
                               "evidence_sha256": evidence_hash, "binding_receipts": bindings})
        return record, bindings, reference, fingerprint, user, normalized, evidence_hash

    def preview(self, actor, request, *, terms=None):
        if type(request) is not dict:
            _fail("request_invalid")
        grant_id = _identifier(request.get("grant_id"))
        with self._transaction() as db:
            self._actor(db, actor)
            rows, current = self._load(db, grant_id)
            prepared = self._prepare(db, actor, request, terms, current, rows, self._now())
            return {"schema": "external-fact-governance-preview@1", **current.summary(now=self._now()),
                    "action": request["action"], "expected_revision": current.revision,
                    "expected_head": current.head, "fingerprint": prepared[3],
                    "proposed_state": prepared[0]["state"], "can_submit": True,
                    "creates_permission": False}

    def append(self, actor, request, *, terms=None, expected_revision, expected_head,
               expected_preview_fingerprint, idempotency_key):
        if (type(request) is not dict or type(expected_revision) is not int or not 0 <= expected_revision <= 255
                or (expected_head is not None and (type(expected_head) is not str or _HASH.fullmatch(expected_head) is None))
                or type(expected_preview_fingerprint) is not str or _HASH.fullmatch(expected_preview_fingerprint) is None
                or type(idempotency_key) is not str):
            _fail("request_invalid")
        try:
            if str(UUID(idempotency_key)) != idempotency_key:
                _fail("request_invalid")
        except ValueError:
            _fail("request_invalid")
        grant_id = _identifier(request.get("grant_id"))
        terms_hash = _terms(terms) if terms is not None else None
        try:
            request_hash = _digest({"request": request, "terms_hash": terms_hash,
                                    "expected_revision": expected_revision, "expected_head": expected_head,
                                    "expected_preview_fingerprint": expected_preview_fingerprint})
        except (TypeError, ValueError, UnicodeError, RecursionError):
            _fail("request_invalid")
        with self._transaction() as db:
            user = self._actor(db, actor)
            rows, current = self._load(db, grant_id)
            replay = db.scalar(select(Revision).where(Revision.actor_user_id == user.id,
                                                       Revision.idempotency_key == idempotency_key))
            if replay is not None:
                if replay.grant_id != grant_id or replay.request_hash != request_hash:
                    _fail("idempotency_conflict")
                return {"schema": "external-fact-governance-result@1", "replayed": True,
                        "historical_event_id": replay.id, "current": current.summary(now=self._now())}
            if expected_revision != current.revision or expected_head != current.head:
                _fail("revision_conflict")
            record, bindings, reference, fingerprint, user, _, evidence_hash = self._prepare(
                db, actor, request, terms, current, rows, self._now())
            if fingerprint != expected_preview_fingerprint:
                _fail("preview_stale")
            evidence = db.get(Evidence, evidence_hash)
            if evidence is None:
                if terms is None:
                    _fail("ledger_invalid")
                db.add(Evidence(raw_hash=evidence_hash, byte_count=len(terms), body=terms))
            elif evidence.byte_count != len(evidence.body) or _terms(evidence.body) != evidence_hash:
                _fail("ledger_invalid")
            now = datetime.fromisoformat(record["review"]["reviewed_at"].replace("Z", "+00:00"))
            row = Revision(id=uid(), grant_id=grant_id, source_id=record["source_id"], revision=record["revision"],
                           record=record, record_digest=record["digest"], previous_digest=current.head,
                           evidence_sha256=evidence_hash, license_reference=reference, binding_receipts=bindings,
                           action=request["action"], actor_user_id=user.id, actor_username_snapshot=user.username,
                           reason=request["reason"], expected_revision=current.revision, expected_head=current.head,
                           preview_fingerprint=fingerprint, idempotency_key=idempotency_key, request_hash=request_hash,
                           audit_event_id=uid(), created_at=now)
            row.event_digest = _event_digest(row)
            audit = AuditEvent(id=row.audit_event_id, session_id="fact_cli:" + UUID(idempotency_key).hex,
                               action="external_fact_policy_changed", detail=_audit_detail(row), created_at=now)
            db.add(audit)
            db.flush()
            db.add(row)
            db.flush()
            _, updated = self._load(db, grant_id)
            return {"schema": "external-fact-governance-result@1", "replayed": False,
                    "historical_event_id": row.id, "current": updated.summary(now=self._now())}
