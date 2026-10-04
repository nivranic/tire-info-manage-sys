"""Explicit, additive PoC migrations; a production migration suite is still future work.

Never invent response validators for historical verifications. Existing rows receive
NULL, so the next request fetches the body unconditionally before validators are used.
"""

from sqlalchemy import DDL, inspect, text
from sqlalchemy.engine import Connection


def _device_ai_ledger_sqlite_statements() -> tuple[str, ...]:
    """Trigger-only additive guards for the two append-only device ledgers.

    BEFORE UPDATE/DELETE raise on any rewrite. The extra BEFORE INSERT guard
    closes the INSERT OR REPLACE gap: SQLite only fires the delete triggers of
    a REPLACE conflict resolution when PRAGMA recursive_triggers=ON, and that
    pragma is per-connection, so a migration can never set it persistently for
    application connections. Any insert already conflicting on a unique key is
    therefore rejected before conflict resolution runs. Plain appends of fresh
    rows pass; a conflicting INSERT OR IGNORE / ON CONFLICT DO NOTHING now also
    fails closed, which is stricter than the ORM guard's allowance yet still
    preserves history.
    """
    conflicts = {
        'device_ai_preparations': ("id = NEW.id"
                                   " OR (actor_session_id = NEW.actor_session_id AND idempotency_key = NEW.idempotency_key)"
                                   " OR (actor_session_id = NEW.actor_session_id AND host_receipt_id = NEW.host_receipt_id)"
                                   " OR (actor_session_id = NEW.actor_session_id AND intent_id = NEW.intent_id)"
                                   " OR ai_pack_id = NEW.ai_pack_id"),
        'device_ai_consent_claims': ("id = NEW.id"
                                     " OR (actor_session_id = NEW.actor_session_id AND analysis_key = NEW.analysis_key)"
                                     " OR preparation_id = NEW.preparation_id"
                                     " OR ai_request_id = NEW.ai_request_id")}
    statements = []
    for table, predicate in conflicts.items():
        for action in ('update', 'delete'):
            statements.append(f'DROP TRIGGER IF EXISTS {table}_no_{action}')
            statements.append(f"CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} BEGIN "
                              "SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END")
        statements.append(f'DROP TRIGGER IF EXISTS {table}_no_replace')
        statements.append(f'CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} '
                          f'WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN '
                          "SELECT RAISE(FAIL, 'device_ai_ledger_immutable'); END")
    return tuple(statements)


DEVICE_AI_LEDGER_TRIGGERS_SQLITE = _device_ai_ledger_sqlite_statements()


def _device_ai_ledger_postgresql_statements() -> tuple[DDL, ...]:
    """PostgreSQL row triggers raising in one shared trigger function.

    PostgreSQL has no INSERT OR REPLACE and ON CONFLICT DO UPDATE fires the
    BEFORE UPDATE trigger, so two triggers per table cover the SQLite insert
    guard's cases here.
    """
    statements = [DDL("CREATE OR REPLACE FUNCTION tire_device_ai_ledger_immutable() RETURNS trigger "
                      "LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'device_ai_ledger_immutable'; END $fn$")]
    for table in ('device_ai_preparations', 'device_ai_consent_claims'):
        for action in ('update', 'delete'):
            statements.append(DDL(f'DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}'))
            statements.append(DDL(f'CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} '
                                  'FOR EACH ROW EXECUTE FUNCTION tire_device_ai_ledger_immutable()'))
    return tuple(statements)


DEVICE_AI_LEDGER_TRIGGERS_POSTGRESQL = _device_ai_ledger_postgresql_statements()


def upgrade(connection: Connection) -> None:
    """Called inside Database.initialize's locked schema transaction."""
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS tire_schema_versions "
        "(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = set(connection.execute(text("SELECT version FROM tire_schema_versions")).scalars())
    if "001_verification_validators" not in applied:
        columns = {column["name"] for column in inspect(connection).get_columns("verifications")}
        for column in ("etag", "last_modified"):
            if column not in columns:
                # Column names are fixed program constants, never external input.
                connection.exec_driver_sql(f"ALTER TABLE verifications ADD COLUMN {column} TEXT")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "001_verification_validators"})
    if "002_monitor_rule_conditions" not in applied:
        columns = {column["name"] for column in inspect(connection).get_columns("alert_rule_revisions")}
        if "conditions" not in columns:
            # Old revisions retain NULL, interpreted as the original no-condition
            # behavior. Do not rewrite immutable historical rule rows.
            connection.exec_driver_sql("ALTER TABLE alert_rule_revisions ADD COLUMN conditions JSON")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "002_monitor_rule_conditions"})
    if "003_parser_release_provenance" not in applied:
        # Unknown legacy identity stays NULL; never assign today's code to old evidence.
        existing = set(inspect(connection).get_table_names())
        for table in ("snapshots", "verifications", "raw_captures", "rejected_observations",
                      "source_quarantines", "vehicle_snapshots", "vehicle_verifications", "vehicle_quarantines"):
            if table in existing:
                columns = {column["name"] for column in inspect(connection).get_columns(table)}
                if "parser_identity" not in columns:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN parser_identity JSON")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "003_parser_release_provenance"})
    if "004_query_selection_filters" not in applied:
        columns = {column["name"] for column in inspect(connection).get_columns("query_runs")}
        if "selection_filters" not in columns:
            # Old query rows stay untouched; SQL NULL means no selection conditions.
            connection.exec_driver_sql("ALTER TABLE query_runs ADD COLUMN selection_filters JSON")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "004_query_selection_filters"})
    if "005_variant_identity_contract" not in applied:
        columns = {column["name"] for column in inspect(connection).get_columns("snapshots")}
        if "identity_contract_version" not in columns:
            # NULL preserves legacy membership and prevents conditional reuse as v2.
            connection.exec_driver_sql("ALTER TABLE snapshots ADD COLUMN identity_contract_version VARCHAR(80)")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "005_variant_identity_contract"})
    if "006_source_settings" not in applied:
        columns = {column["name"] for column in inspect(connection).get_columns("query_runs")}
        if "source_access_generation" not in columns:
            # Legacy requests never acquired a source-management pin. Keep NULL;
            # do not manufacture authorization for their pending consents.
            connection.exec_driver_sql("ALTER TABLE query_runs ADD COLUMN source_access_generation INTEGER")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "006_source_settings"})
    if "007_monitor_tasks" not in applied:
        # create_all registered only the two new receipt tables. Old jobs and
        # terminal runs retain their real history; no stages are manufactured.
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "007_monitor_tasks"})
    if "008_recall_discovery_monitoring" not in applied:
        # create_all adds seven discovery domain tables and two dedicated journal
        # tables. Existing task checks, rows, indexes and cursors stay unchanged.
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "008_recall_discovery_monitoring"})
    if "009_ai_streaming" not in applied:
        # Only two additive stream receipt tables; AIRequest/AICompletion remain
        # the original immutable budget and answer ledgers.
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "009_ai_streaming"})
    if "010_offline_packs" not in applied:
        # Only the two additive immutable offline tables; old evidence stays intact.
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "010_offline_packs"})
    if "011_query_fallback_policies" not in applied:
        # Three new metadata/permission ledgers only. Existing once consents,
        # source pins, facts, snapshots and all old rows are unchanged.
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "011_query_fallback_policies"})
    if "012_device_ai_preparations" not in applied:
        # create_all registers only the two additive device ledgers. No prior
        # preparations, host receipts or consent claims exist, so none are
        # manufactured; every old table and row stays exactly as it was.
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "012_device_ai_preparations"})
    if "013_device_ai_ledger_triggers" not in applied:
        # Version number confirmed by Root (2026-10-03; roundtable open
        # question 3 resolved); a collision changes only this version string,
        # never the DDL. Defense in depth over protect_device_ai_history's ORM/Core
        # guard: raw text()/exec_driver_sql statements and future migrations
        # hit these triggers instead of rewriting the append-only ledgers.
        # Idempotent rebuild: every CREATE is preceded by DROP ... IF EXISTS.
        if connection.dialect.name == 'postgresql':
            for statement in DEVICE_AI_LEDGER_TRIGGERS_POSTGRESQL:
                connection.execute(statement)
        else:
            for statement in DEVICE_AI_LEDGER_TRIGGERS_SQLITE:
                connection.exec_driver_sql(statement)
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "013_device_ai_ledger_triggers"})
    if "014_local_sessions_user" not in applied:
        # 多用户账户：local_sessions 加可空 user_id（照 006 先例，裸列不带 FK 约束）。
        # users 表由 create_all 以 ORM 模型建出；既有会话保持 NULL（匿名）。
        columns = {column["name"] for column in inspect(connection).get_columns("local_sessions")}
        if "user_id" not in columns:
            # Column names are fixed program constants, never external input.
            connection.exec_driver_sql("ALTER TABLE local_sessions ADD COLUMN user_id VARCHAR(64)")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "014_local_sessions_user"})
    if "015_local_sessions_user_index" not in applied:
        # G2-1（第61轮圆桌）：014 只加列未建索引，而 ORM 的 index=True 仅在新库
        # create_all 时生效——升级库与新建库 schema 不同构，session_scope 按
        # user_id 过滤退化为全表扫描。幂等补建两路径共同的索引。
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_local_sessions_user_id ON local_sessions (user_id)")
        connection.execute(text(
            "INSERT INTO tire_schema_versions (version) VALUES (:version)"
        ), {"version": "015_local_sessions_user_index"})
