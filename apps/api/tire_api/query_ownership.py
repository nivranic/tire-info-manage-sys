"""Server-issued new-query ownership, independent of mutable session bindings.

This first implementation enables SQLite writes/reads only. A private issuer is
an accidental-misuse check, not protection against malicious trusted Python code.
Callers still authenticate API keys and evaluate current license/field policy.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from .db import AuditEvent, QueryRun, User, UserSession, uid, utc, utcnow
from .domain import digest
from .query_owner_models import QueryRunOwnerReceipt, SCHEMA

_ISSUER = object()
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HASH = re.compile(r"[0-9a-f]{64}")


class QueryOwnershipError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise QueryOwnershipError(code)


def _now(value):
    value = utcnow() if value is None else value
    if type(value) is not datetime or value.tzinfo is not UTC:
        _fail("query_actor_invalid")
    return value


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clean(db):
    # lock_ingestion commits before BEGIN IMMEDIATE. Never flush/commit another
    # caller's pending writes, or enter an independently owned G1b connection.
    if (db.new or db.dirty or db.deleted or db.in_nested_transaction()
            or not isinstance(db.get_bind(), Engine)):
        _fail("query_owner_transaction_invalid")


def _rollback(db):
    # A commit acknowledgement/after_commit callback can fail after durability.
    # In that state rollback itself may be invalid; it must not replace the safe
    # fixed error or be described as proof that committed rows were removed.
    try:
        db.rollback()
    except Exception:
        pass


@dataclass(frozen=True, slots=True, repr=False)
class _QueryActor:
    session_id: str
    user_id: str
    captured_at: datetime
    issuer: object = field(repr=False)
    db_marker: object = field(repr=False)


def capture_query_actor(db, session_id, *, now=None):
    """Only the server live-query adapter supplies request.state.session_id.

    None freezes anonymous/unsupported-backend admission; a later login cannot
    upgrade it. No password, Cookie, Bearer or request-supplied owner is accepted.
    This capture starts from a clean, fresh request Session.
    """
    if db.get_bind().dialect.name != "sqlite":
        return None
    _clean(db)
    if db.in_transaction() or not _id(session_id):
        _fail("query_owner_transaction_invalid" if db.in_transaction() else "query_actor_invalid")
    now = _now(now)
    row = db.execute(select(UserSession.user_id, UserSession.expires_at)
                     .where(UserSession.id == session_id)).first()
    if row is None:
        _fail("query_actor_invalid")
    if row.user_id is None:
        return None
    if (not _id(row.user_id) or utc(row.expires_at) <= now
            or db.scalar(select(User.id).where(User.id == row.user_id)) is None):
        _fail("query_actor_invalid")
    return _QueryActor(session_id, row.user_id, now.replace(microsecond=0), _ISSUER, db)


def _actor(db, actor, session_id, now):
    if (type(actor) is not _QueryActor or actor.issuer is not _ISSUER or actor.db_marker is not db
            or actor.session_id != session_id or not _id(actor.user_id)
            or type(actor.captured_at) is not datetime or actor.captured_at.tzinfo is not UTC
            or actor.captured_at.microsecond != 0 or actor.captured_at > now):
        _fail("query_actor_invalid")
    # Column rows bypass expire_on_commit=False identity-map objects. SQLite's
    # BEGIN IMMEDIATE serializes with the unchanged auth login/logout/delete.
    row = db.execute(select(UserSession.user_id, UserSession.expires_at)
                     .where(UserSession.id == session_id)).first()
    if (row is None or row.user_id != actor.user_id or utc(row.expires_at) <= now
            or db.scalar(select(User.id).where(User.id == actor.user_id)) is None):
        _fail("query_actor_changed")


def query_binding_digest(run):
    try:
        if (not _id(run.id) or not _id(run.session_id) or type(run.source_id) is not str
                or not run.source_id or len(run.source_id) > 80
                or type(run.query) is not dict or type(run.query_key) is not str
                or _HASH.fullmatch(run.query_key) is None or digest(run.query) != run.query_key
                or (run.selection_filters is not None and type(run.selection_filters) is not list)):
            _fail("query_owner_binding_invalid")
        return digest({"query_id": run.id, "session_id": run.session_id, "source_id": run.source_id,
                       "query_key": run.query_key, "query": run.query, "selection_filters": run.selection_filters})
    except (TypeError, ValueError, OverflowError, UnicodeError):
        _fail("query_owner_binding_invalid")


def _record_digest(row):
    return digest({"schema": row.schema, "query_id": row.query_id, "owner_user_id": row.owner_user_id,
                   "actor_session_id": row.actor_session_id, "query_binding_digest": row.query_binding_digest,
                   "audit_event_id": row.audit_event_id,
                   "captured_at": utc(row.captured_at).strftime("%Y-%m-%dT%H:%M:%SZ")})


def _validate(db, run, row, *, budget=None):
    try:
        audit = (db.get(AuditEvent, row.audit_event_id, populate_existing=True) if budget is None else
                 budget.get(db, AuditEvent, row.audit_event_id, limits={"detail": 16 * 1024}))
        if (row.schema != SCHEMA or row.query_id != run.id or not _id(row.owner_user_id)
                or row.actor_session_id != run.session_id or not _id(row.audit_event_id)
                or row.query_binding_digest != query_binding_digest(run)
                or type(row.captured_at) is not datetime or row.captured_at.microsecond != 0
                or type(row.record_digest) is not str or _HASH.fullmatch(row.record_digest) is None
                or row.record_digest != _record_digest(row)
                or audit is None or audit.session_id != row.actor_session_id or audit.query_id != run.id
                or audit.action != "online_query_started" or audit.consent_id is not None
                or audit.detail != {"source_id": run.source_id, "query_owner_schema": SCHEMA,
                                    "query_owner_digest": row.record_digest}):
            _fail("query_owner_binding_invalid")
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError, ValueError):
        _fail("query_owner_binding_invalid")
    return row


def require_query_owner(db, query_id, owner_user_id, *, budget=None):
    """Validate one receipt in the caller's existing transaction; no commit.

    Authentication/current key, policy, formal Verification/Snapshot binding and
    projection must be checked by the future owned reader in this same context.
    This helper alone does not authorize external facts or expose HTTP routes.
    """
    if db.get_bind().dialect.name != "sqlite":
        _fail("query_owner_backend_unsupported")
    if not db.in_transaction() or db.new or db.dirty or db.deleted:
        _fail("query_owner_transaction_invalid")
    if not _id(query_id) or not _id(owner_user_id):
        _fail("query_owner_not_found")
    row = (db.get(QueryRunOwnerReceipt, query_id, populate_existing=True) if budget is None else
           budget.get(db, QueryRunOwnerReceipt, query_id))
    if (row is None or row.owner_user_id != owner_user_id
            or (db.scalar(select(User.id).where(User.id == owner_user_id)) if budget is None else
                next(iter(budget.load(db, User, User.id == owner_user_id, columns=("id",))), None)) is None):
        _fail("query_owner_not_found")
    run = (db.get(QueryRun, query_id, populate_existing=True) if budget is None else
           budget.get(db, QueryRun, query_id, limits={"query": 64 * 1024, "selection_filters": 64 * 1024}))
    if run is None:
        _fail("query_owner_binding_invalid")
    return _validate(db, run, row, budget=budget)


def create_query_with_owner(db, run, actor, *, lock_ingestion, now=None):
    """Atomically persist a new QueryRun, its existing audit and one receipt.

    Internal same-ID replay only validates an already complete triple. It never
    retrofits old queries, changes owners or creates a second audit event.
    """
    if db.get_bind().dialect.name != "sqlite":
        _fail("query_owner_backend_unsupported")
    _clean(db)
    if type(run) is not QueryRun or not inspect(run).transient:
        _fail("query_owner_conflict")
    # Validate the issuer before lock_ingestion's pre-commit.
    if type(actor) is not _QueryActor or actor.issuer is not _ISSUER or actor.db_marker is not db:
        _fail("query_actor_invalid")
    commit_started = False
    try:
        binding = query_binding_digest(run)
        lock_ingestion()
        # Read the real clock after any lock wait, not before an expired actor
        # could have waited for another SQLite writer to finish.
        _actor(db, actor, run.session_id, _now(now))
        existing = db.get(QueryRun, run.id, populate_existing=True)
        if existing is not None:
            row = db.get(QueryRunOwnerReceipt, run.id, populate_existing=True)
            if (row is None or row.owner_user_id != actor.user_id or row.actor_session_id != actor.session_id
                    or row.query_binding_digest != binding or existing.fallback_policy != run.fallback_policy):
                _fail("query_owner_conflict")
            try:
                _validate(db, existing, row)
            except QueryOwnershipError:
                _fail("query_owner_conflict")
            db.rollback()
            return existing
        audit = AuditEvent(id=uid(), session_id=run.session_id, action="online_query_started",
                           query_id=run.id, detail={"source_id": run.source_id})
        row = QueryRunOwnerReceipt(schema=SCHEMA, query_id=run.id, owner_user_id=actor.user_id,
            actor_session_id=actor.session_id, query_binding_digest=binding,
            audit_event_id=audit.id, captured_at=actor.captured_at, record_digest="")
        row.record_digest = _record_digest(row)
        audit.detail = {**audit.detail, "query_owner_schema": SCHEMA, "query_owner_digest": row.record_digest}
        # Explicit flush order makes FK dependencies unambiguous without adding
        # ORM relationships/cascades to the historical query/audit models.
        db.add(run)
        db.flush()
        db.add(audit)
        db.flush()
        db.add(row)
        db.flush()
        commit_started = True
        db.commit()
        return run
    except QueryOwnershipError:
        _rollback(db)
        if commit_started:
            _fail("query_owner_commit_unconfirmed")
        raise
    except IntegrityError:
        _rollback(db)
        if commit_started:
            _fail("query_owner_commit_unconfirmed")
        _fail("query_owner_conflict")
    except Exception:
        _rollback(db)
        if commit_started:
            _fail("query_owner_commit_unconfirmed")
        _fail("query_owner_write_failed")
    except BaseException:
        _rollback(db)
        raise
