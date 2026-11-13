"""Fixed SQL for owned evidence reads; no request-controlled identifiers.

PostgreSQL locks are acquired before any authorization read, in READ COMMITTED.
Table SHARE locks also exclude writers that do not use the ingestion mutex.
The caller owns commit/rollback; this module never opens a connection.
"""
from sqlalchemy import JSON, LargeBinary, Text, case, cast, func, literal


READER_TABLES = (
    'audit_events', 'external_api_key_revocations', 'external_api_keys',
    'external_fact_grant_revisions', 'external_fact_license_evidence',
    'fact_versions', 'identity_revisions', 'manual_fact_revisions',
    'query_run_owner_receipts', 'query_runs', 'safety_gate_snapshots',
    'safety_gate_verifications', 'snapshots', 'tire_schema_versions',
    'tire_variants', 'users', 'variant_identity_bindings',
    'variant_lifecycle_events', 'verifications',
)
OWNER_TABLES = ('local_sessions', 'users')


def postgres_boundary(connection, *, owner_write=False):
    """Fresh transaction only: serialize first, then freeze the declared tables.

    SHARE needs a read-write transaction. The reader's restricted Session still
    rejects writes/commit; this is trusted application code, not a SQL sandbox.
    SET LOCAL values disappear on both commit and rollback (including pooling).
    """
    connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
    connection.exec_driver_sql("SET LOCAL lock_timeout = '2000ms'")
    connection.exec_driver_sql("SET LOCAL statement_timeout = '5000ms'")
    connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout = '15000ms'")
    connection.exec_driver_sql('SELECT pg_advisory_xact_lock(821741905)')
    tables = OWNER_TABLES if owner_write else READER_TABLES
    connection.exec_driver_sql('LOCK TABLE ' + ', '.join(tables) + ' IN SHARE MODE')


def storage_bytes(db, column):
    """Count UTF-8 text/JSON bytes without interpreting backslashes as bytea."""
    if db.get_bind().dialect.name == 'postgresql':
        if isinstance(column.type, LargeBinary):
            return func.octet_length(column)
        return func.octet_length(func.convert_to(cast(column, Text), 'UTF8'))
    return func.length(cast(cast(column, Text), LargeBinary))


def json_valid(db, column):
    # PostgreSQL JSON columns reject invalid JSON at write time. NULL remains
    # invalid here, like SQLite json_valid(NULL); JSON null is valid syntax.
    if db.get_bind().dialect.name == 'postgresql':
        return case((column.is_not(None), literal(1)), else_=literal(0))
    return func.json_valid(column)


def json_array_length(db, column):
    if db.get_bind().dialect.name == 'postgresql':
        value = cast(column, JSON)
        return case((func.json_typeof(value) == 'array', func.json_array_length(value)), else_=None)
    return func.json_array_length(column)
