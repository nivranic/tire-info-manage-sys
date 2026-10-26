"""Explicit private SQLite rehearsal for the vehicle binary schema change.

Normal startup only inspects schema. The managed entrypoint owns its connection,
preserves original rows in memory, and never changes object or Parser bundle files.
It does not certify a normal-database deployment or audit those external assets.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text


VERSION = "024_vehicle_binary_raw"
PRIOR_VERSION = "023_external_api_keys"
VEHICLE_TABLES = ("vehicle_snapshots", "vehicle_quarantines")
RAW_TABLES = ("raw_captures", "rejected_observations")
TARGET_TABLES = VEHICLE_TABLES + RAW_TABLES
# Frozen 023 ORM table boundary, reviewed against its original schema and
# explicit model closure. Later model registration must not extend this list.
# The migration ledger and FTS virtual/shadow tables are not ORM tables.
PRIOR_MODEL_TABLES = (
    "ai_completions", "ai_draft_applications", "ai_evidence_packs",
    "ai_requests", "ai_stream_events", "ai_stream_executions",
    "alert_events", "alert_rule_revisions", "alert_rules",
    "audit_events", "candidate_ai_authorizations", "candidate_ai_claims",
    "candidate_ai_preparations", "capture_objects", "change_events",
    "device_ai_consent_claims", "device_ai_preparations", "driving_preference_revisions",
    "embedding_cache", "embedding_completions", "embedding_plans",
    "embedding_requests", "evidence_documents", "evidence_objects",
    "external_api_key_minutes", "external_api_key_operations", "external_api_key_revocations",
    "external_api_keys", "fact_versions", "fallback_consents",
    "fitment_relation_revisions", "fitment_relations", "garage_revisions",
    "garage_vehicles", "golden_case_reviews", "golden_case_revisions",
    "golden_cases", "golden_set_revisions", "identity_revisions",
    "interest_events", "interest_notifications", "interest_revisions",
    "interests", "knowledge_documents", "knowledge_facets",
    "knowledge_index_state", "local_sessions", "manual_fact_revisions",
    "monitor_jobs", "monitor_runs", "monitor_task_attempts",
    "monitor_task_events", "notification_deliveries", "offline_pack_plans",
    "offline_packs", "parser_bundles", "parser_deployment_revisions",
    "parser_evaluation_completions", "parser_evaluation_reviews", "parser_evaluations",
    "parser_executions", "parser_selections", "quarantine_approval_uses",
    "quarantine_reviews", "query_fallback_policy_revisions", "query_fallback_previews",
    "query_fallback_uses", "query_runs", "raw_captures",
    "recall_discovery_candidates", "recall_discovery_jobs", "recall_discovery_notifications",
    "recall_discovery_pages", "recall_discovery_rule_revisions", "recall_discovery_rules",
    "recall_discovery_runs", "recall_discovery_task_attempts", "recall_discovery_task_events",
    "recall_events", "recall_monitor_jobs", "recall_monitor_rules",
    "recall_monitor_runs", "recall_notifications", "recall_revisions",
    "recall_rule_revisions", "recall_search_snapshots", "recall_search_verifications",
    "recall_snapshots", "recall_verifications", "rejected_observations",
    "reparse_completions", "reparse_reviews", "reparse_runs",
    "report_exports", "research_report_revisions", "research_reports",
    "saved_comparison_revisions", "saved_comparisons", "snapshots",
    "source_material_outcomes", "source_material_requests", "source_quarantines",
    "source_setting_revisions", "test_event_revisions", "test_events",
    "test_sku_link_revisions", "test_sku_links", "tire_catalog_revisions",
    "tire_curation_applicability_events", "tire_variants", "users",
    "variant_identity_bindings", "variant_identity_migration_applications", "variant_lifecycle_events",
    "vehicle_manufacturers", "vehicle_models", "vehicle_quarantines",
    "vehicle_snapshots", "vehicle_trims", "vehicle_verifications",
    "vehicle_wheel_fitments", "verifications", "watch_items",
    "webhook_attempts", "webhook_completions", "webhook_dispatch_slots",
    "webhook_envelopes", "webhook_operations", "webhook_overflows",
    "webhook_queue", "webhook_revisions", "webhook_statistics",
    "webhook_subscriptions", "webhook_target_slots",
)
MAX_BYTES = 8 * 1024 * 1024
TEXT_MIMES = frozenset({"text/html", "application/json", "text/javascript", "application/javascript", "text/plain"})
ENCODING_CHECK = "body_encoding IN ('utf-8', 'binary')"
VEHICLE_STORAGE_CHECK = (
    "(body_encoding = 'utf-8' AND body IS NOT NULL AND length(body) > 0 AND content_type = 'application/json') OR "
    "(body_encoding = 'binary' AND body IS NULL AND raw_capture_id IS NOT NULL AND content_type = 'application/pdf' "
    "AND source_id = 'xiaomi-cn-vehicles' AND vehicle_id = 'xiaomi-su7-first-generation')"
)
RAW_STORAGE_CHECK = (
    "body_encoding = 'utf-8' OR (body_encoding = 'binary' AND source_id = 'xiaomi-cn-vehicles' "
    "AND target_kind = 'vehicle' AND content_type = 'application/pdf')"
)
RAW_SIZE_CHECK = "typeof(raw_body) = 'blob' AND byte_count >= 1 AND byte_count <= 8388608 AND byte_count = length(raw_body)"
PG_RAW_SIZE_CHECK = "byte_count >= 1 AND byte_count <= 8388608 AND byte_count = length(raw_body)"
FAILURE_STAGES = ("after_copy", "after_replace", "before_version", "before_commit")


class VehicleBinaryMigrationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code="vehicle_binary_schema_inconsistent"):
    if not condition:
        raise VehicleBinaryMigrationError(code)


def _quote(value):
    return '"' + value.replace('"', '""') + '"'


def _rows(connection, sql, parameters=()):
    cursor = (connection.exec_driver_sql(sql, parameters) if hasattr(connection, "exec_driver_sql")
              else connection.execute(sql, parameters))
    try:
        return [tuple(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _execute(connection, sql, parameters=()):
    cursor = (connection.exec_driver_sql(sql, parameters) if hasattr(connection, "exec_driver_sql")
              else connection.execute(sql, parameters))
    cursor.close()


def _check_expression(sql):
    """Parse only this migration's CHECK grammar, including PostgreSQL deparse.

    Boolean grouping is retained. Text/varchar casts are representation-only for
    the separately verified varchar columns; unknown SQL is rejected, not guessed.
    """
    pieces = re.split(r'''('(?:''|[^'])*'|"(?:""|[^"])*")''', sql)
    for index in range(0, len(pieces), 2):
        pieces[index] = re.sub(r"::\s*(?:character\s+varying|text)(?:\[\])?", "", pieces[index], flags=re.IGNORECASE)
    sql = "".join(pieces)
    pattern = re.compile(r'''\s*(?:('(?:''|[^'])*')|("(?:""|[^"])*")|([A-Za-z_][A-Za-z_0-9]*)|(\d+)|(>=|<=|<>|!=|[=><(),\[\]]))''')
    tokens = []
    offset = 0
    while offset < len(sql):
        if not sql[offset:].strip():
            break
        match = pattern.match(sql, offset)
        _require(match is not None)
        string, quoted, word, number, symbol = match.groups()
        token = (("literal", string[1:-1].replace("''", "'")) if string is not None else
                 ("name", quoted[1:-1].replace('""', '"')) if quoted is not None else
                 ("number", int(number)) if number is not None else (word.lower() if word is not None else symbol))
        tokens.append(token)
        offset = match.end()
    position = 0
    def take(expected=None):
        nonlocal position
        _require(position < len(tokens))
        token = tokens[position]
        _require(expected is None or token == expected)
        position += 1
        return token
    def peek():
        return tokens[position] if position < len(tokens) else None
    def combine(operator, left, right):
        values = []
        for value in (left, right):
            values.extend(value[1] if value[0] == operator else [value])
        return (operator, tuple(sorted(values, key=repr)))
    def expression(minimum=0):
        token = take()
        if token == "(":
            left = expression()
            take(")")
        elif token == "array" and peek() == "[":
            take("[")
            values = [expression()]
            while peek() == ",":
                take(",")
                values.append(expression())
            take("]")
            _require(all(isinstance(value, tuple) and value[0] == "literal" for value in values))
            left = ("array", tuple(sorted(values, key=repr)))
        elif isinstance(token, tuple):
            left = token
        else:
            _require(isinstance(token, str) and re.fullmatch(r"[a-z_][a-z_0-9]*", token) is not None)
            left = ("name", token)
        if peek() == "(":
            _require(left in (("name", "length"), ("name", "octet_length"), ("name", "typeof"), ("name", "any")))
            take("(")
            argument = expression()
            take(")")
            left = (left[1] if left in (("name", "typeof"), ("name", "any")) else "length", argument)
        precedence = {"or": 1, "and": 2, "=": 3, ">=": 3, "<=": 3, ">": 3, "<": 3, "is": 3, "in": 3}
        while isinstance(peek(), str) and peek() in precedence and precedence[peek()] >= minimum:
            operator = take()
            level = precedence[operator]
            if operator == "is":
                negated = peek() == "not"
                if negated:
                    take("not")
                take("null")
                left = ("is_not_null" if negated else "is_null", left)
            elif operator == "in":
                take("(")
                values = [take()]
                while peek() == ",":
                    take(",")
                    values.append(take())
                take(")")
                _require(all(isinstance(value, tuple) and value[0] == "literal" for value in values))
                left = ("in", left, tuple(sorted(values, key=repr)))
            else:
                right = expression(level + 1)
                if operator == "=" and right[0] == "any":
                    _require(right[1][0] == "array")
                    left = ("in", left, right[1][1])
                else:
                    left = combine(operator, left, right) if operator in {"and", "or"} else (operator, left, right)
        return left
    result = expression()
    _require(position == len(tokens))
    return result


def _checks_for(table, dialect="sqlite"):
    checks = {f"ck_{table}_body_encoding": ENCODING_CHECK,
              f"ck_{table}_body_storage": VEHICLE_STORAGE_CHECK if table in VEHICLE_TABLES else RAW_STORAGE_CHECK}
    if table == "raw_captures":
        checks["ck_raw_captures_byte_count"] = PG_RAW_SIZE_CHECK if dialect == "postgresql" else RAW_SIZE_CHECK
    return checks


def _sqlite_objects(connection):
    return {(kind, name): (table, sql) for kind, name, table, sql in _rows(connection,
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")}


def _columns(connection, table):
    return {row[1]: row for row in _rows(connection, "PRAGMA table_info(" + _quote(table) + ")")}


def _versions(connection, tables):
    return {row[0] for row in _rows(connection, "SELECT version FROM tire_schema_versions")} if "tire_schema_versions" in tables else set()


def _closing_paren(sql, start):
    sql = _sql_code_mask(sql)
    depth, quote = 0, None
    index = start
    while index < len(sql):
        character = sql[index]
        if quote:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in "'\"`":
            quote = character
        elif character == "[":
            quote = "]"
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise VehicleBinaryMigrationError("vehicle_binary_schema_inconsistent")


def _sql_code_mask(sql, *, mask_identifiers=False):
    """Keep offsets, masking string literals/comments without treating them as DDL."""
    output = list(sql)
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = len(sql) if end < 0 else end
            output[index:end] = " " * (end - index)
            index = end
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            _require(end >= 0)
            end += 2
            output[index:end] = " " * (end - index)
            index = end
        elif sql[index] in "'\"`[":
            opening = sql[index]
            closing = "]" if opening == "[" else opening
            end = index + 1
            while end < len(sql):
                if sql[end] == closing:
                    if end + 1 < len(sql) and sql[end + 1] == closing:
                        end += 2
                        continue
                    break
                end += 1
            _require(end < len(sql))
            end += 1
            if opening == "'" or mask_identifiers:
                output[index:end] = " " * (end - index)
            index = end
        else:
            index += 1
    return "".join(output)


def _named_checks(sql):
    result = {}
    pattern = r'\bCONSTRAINT\s+(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))\s+CHECK\s*\('
    masked = _sql_code_mask(sql)
    keywords = _sql_code_mask(sql, mask_identifiers=True)
    for match in re.finditer(pattern, masked, re.IGNORECASE):
        if keywords[match.start():match.start() + 10].upper() != "CONSTRAINT":
            continue
        start = match.end() - 1
        name = next(value for value in match.groups() if value is not None)
        _require(name not in result)
        result[name] = sql[start + 1:_closing_paren(sql, start)]
    return result


def _required_relationships(connection):
    required = {"vehicle_quarantines": "previous_snapshot_id", "vehicle_verifications": "snapshot_id",
                "vehicle_wheel_fitments": "snapshot_id"}
    dialect = getattr(getattr(connection, "dialect", None), "name", "sqlite")
    for table, column in required.items():
        if dialect == "sqlite":
            foreign_keys = _rows(connection, "PRAGMA foreign_key_list(" + _quote(table) + ")")
            _require(sum(row[2] == "vehicle_snapshots" and row[3] == column and row[4] == "id" for row in foreign_keys) == 1)
        else:
            _require(sum(item["referred_table"] == "vehicle_snapshots" and item["constrained_columns"] == [column]
                         and item["referred_columns"] == ["id"] for item in inspect(connection).get_foreign_keys(table)) == 1)


def schema_state(connection):
    """Read-only classification. A current shape may still have an older ledger."""
    dialect = getattr(getattr(connection, "dialect", None), "name", "sqlite")
    if dialect != "sqlite":
        _require(dialect == "postgresql", "vehicle_binary_unsupported_backend")
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if not tables:
            return "empty"
        _require(set(TARGET_TABLES) <= tables)
        versions = {row[0] for row in connection.execute(text("SELECT version FROM tire_schema_versions"))} if "tire_schema_versions" in tables else set()
        columns = {table: {column["name"]: column for column in inspector.get_columns(table)} for table in TARGET_TABLES}
        present = ["body_encoding" in columns[table] for table in TARGET_TABLES]
        references = ["raw_capture_id" in columns[table] for table in VEHICLE_TABLES]
        if not any(present + references):
            _require(VERSION not in versions and all(columns[table]["body"]["nullable"] is False for table in VEHICLE_TABLES))
            return "legacy"
        _require(all(present + references))
        for table in TARGET_TABLES:
            required = ("source_id", "vehicle_id", "content_type", "raw_hash") if table in VEHICLE_TABLES else (
                "source_id", "target_kind", "content_type", "raw_hash", "raw_body")
            if table == "raw_captures":
                required += ("byte_count",)
            _require(all(columns[table][name]["nullable"] is False for name in required))
            encoding = columns[table]["body_encoding"]
            _require(str(encoding["type"]).upper() == "VARCHAR(16)" and encoding["nullable"] is False
                     and _check_expression(str(encoding["default"])) == ("literal", "utf-8"))
            constraints = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints(table)}
            for name, expression in _checks_for(table, "postgresql").items():
                _require(name in constraints and _check_expression(constraints[name]) == _check_expression(expression))
            if table in VEHICLE_TABLES:
                _require(columns[table]["body"]["nullable"] is True and columns[table]["raw_capture_id"]["nullable"] is True
                         and str(columns[table]["body"]["type"]).upper() == "TEXT"
                         and columns[table]["raw_capture_id"]["default"] is None
                         and str(columns[table]["raw_capture_id"]["type"]).upper() == "VARCHAR(64)")
                foreign_keys = inspector.get_foreign_keys(table)
                _require(sum(item["referred_table"] == "raw_captures" and item["constrained_columns"] == ["raw_capture_id"]
                             and item["referred_columns"] == ["id"] and item.get("options", {}).get("ondelete") == "RESTRICT"
                             for item in foreign_keys) == 1)
                indexes = {item["name"]: item for item in inspector.get_indexes(table)}
                name = "ix_" + table + "_raw_capture_id"
                _require(name in indexes and not indexes[name]["unique"] and indexes[name]["column_names"] == ["raw_capture_id"]
                         and not indexes[name].get("dialect_options", {}).get("postgresql_where"))
                _require(not any(item["unique"] and item["column_names"] == ["raw_capture_id"] for item in indexes.values())
                         and not any(item["column_names"] == ["raw_capture_id"] for item in inspector.get_unique_constraints(table)))
        _required_relationships(connection)
        return "current"
    objects = _sqlite_objects(connection)
    tables = {name for kind, name in objects if kind == "table" and not name.startswith("sqlite_")}
    if not tables:
        return "empty"
    _require(set(TARGET_TABLES) <= tables)
    versions = _versions(connection, tables)
    columns = {table: _columns(connection, table) for table in TARGET_TABLES}
    present = ["body_encoding" in columns[table] for table in TARGET_TABLES]
    references = ["raw_capture_id" in columns[table] for table in VEHICLE_TABLES]
    if not any(present + references):
        _require(VERSION not in versions and all(columns[table]["body"][3] == 1 for table in VEHICLE_TABLES))
        return "legacy"
    _require(all(present + references))
    for table in TARGET_TABLES:
        required = ("source_id", "vehicle_id", "content_type", "raw_hash") if table in VEHICLE_TABLES else (
            "source_id", "target_kind", "content_type", "raw_hash", "raw_body")
        if table == "raw_captures":
            required += ("byte_count",)
        _require(all(columns[table][name][3] == 1 for name in required))
        encoding = columns[table]["body_encoding"]
        _require(encoding[2].upper() == "VARCHAR(16)" and encoding[3] == 1
                 and _check_expression(str(encoding[4])) == ("literal", "utf-8"))
        actual_checks = _named_checks(objects[("table", table)][1])
        for name, expression in _checks_for(table).items():
            _require(name in actual_checks and _check_expression(actual_checks[name]) == _check_expression(expression))
        if table in VEHICLE_TABLES:
            _require(columns[table]["body"][3] == 0 and columns[table]["raw_capture_id"][3] == 0
                     and columns[table]["body"][2].upper() == "TEXT" and columns[table]["raw_capture_id"][4] is None
                     and columns[table]["raw_capture_id"][2].upper() == "VARCHAR(64)")
            foreign_keys = _rows(connection, "PRAGMA foreign_key_list(" + _quote(table) + ")")
            _require(sum(fk[2] == "raw_captures" and fk[3] == "raw_capture_id" and fk[4] == "id"
                         and fk[6].upper() == "RESTRICT" for fk in foreign_keys) == 1)
            indexes = {row[1]: row for row in _rows(connection, "PRAGMA index_list(" + _quote(table) + ")")}
            name = "ix_" + table + "_raw_capture_id"
            _require(name in indexes and indexes[name][2] == 0 and indexes[name][4] == 0
                     and [row[2] for row in _rows(connection, "PRAGMA index_info(" + _quote(name) + ")")] == ["raw_capture_id"])
            _require(not any(item[2] == 1 and [row[2] for row in _rows(connection,
                         "PRAGMA index_info(" + _quote(item[1]) + ")")] == ["raw_capture_id"] for item in indexes.values()))
    _required_relationships(connection)
    return "current"


def _new_sqlite_application_schema(connection):
    """Recognize unrelated user objects without importing or creating models.

    Current metadata only identifies ownership conflicts. It is never an
    expected definition for the fixed historical 023 migration predecessor.
    """
    from .db import Base

    reserved = {
        "tire_schema_versions", "knowledge_fts", "knowledge_fts_data", "knowledge_fts_idx",
        "knowledge_fts_content", "knowledge_fts_docsize", "knowledge_fts_config",
        "embedding_vectors", "ix_embedding_vector_space", "ix_knowledge_search_vector",
    }
    # These model modules need not have been registered by non-Web startup.
    owned_tables = {table.name for table in Base.metadata.tables.values()} | {
        "research_reports", "research_report_revisions", "report_exports",
        "reparse_runs", "reparse_completions", "reparse_reviews",
    }
    reserved.update(owned_tables)
    reserved.update(index.name for table in Base.metadata.tables.values()
                    for index in table.indexes if index.name is not None)
    # Existing IF NOT EXISTS guards must not be shadowed by a user trigger.
    reserved.update(table + suffix for table in owned_tables
                    for suffix in ("_no_update", "_no_delete", "_no_replace"))
    reserved = {name.casefold() for name in reserved}
    return not any(name.casefold() in reserved or table.casefold() in reserved
                   for (_, name), (table, _) in _sqlite_objects(connection).items())


def preflight(connection):
    sqlite = getattr(getattr(connection, "dialect", None), "name", "sqlite") == "sqlite"
    if sqlite and _new_sqlite_application_schema(connection):
        return "empty"
    state = schema_state(connection)
    # A conflicting view can leave the strict classifier's table set empty.
    if sqlite:
        _require(state != "empty")
    if state == "legacy":
        raise VehicleBinaryMigrationError("vehicle_binary_migration_required")
    return state


def require_current(connection):
    _require(schema_state(connection) == "current")


def _records(connection, table):
    columns = list(_columns(connection, table))
    return [dict(zip(columns, row, strict=True)) for row in _rows(connection,
        "SELECT " + ",".join(map(_quote, columns)) + " FROM " + _quote(table))]


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _validate_evidence(connection):
    """Only fixed integrity errors escape; no row or credential digest is logged."""
    try:
        objects = _sqlite_objects(connection)
        tables = {name for kind, name in objects if kind == "table"}
        query_rows = {row["id"]: row for row in _records(connection, "query_runs")}
        captures = {row["id"]: row for row in _records(connection, "raw_captures")}
        snapshots = {row["id"]: row for row in _records(connection, "vehicle_snapshots")}
        quarantines = {row["id"]: row for row in _records(connection, "vehicle_quarantines")}
        for table in RAW_TABLES:
            for row in _records(connection, table):
                raw = row["raw_body"]
                _require(row.get("body_encoding", "utf-8") == "utf-8", "vehicle_binary_invalid_legacy_evidence")
                _require(isinstance(raw, bytes) and 1 <= len(raw) <= MAX_BYTES and row["content_type"] in TEXT_MIMES,
                         "vehicle_binary_invalid_legacy_evidence")
                raw.decode("utf-8", errors="strict")
                _require(hashlib.sha256(raw).hexdigest() == row["raw_hash"], "vehicle_binary_invalid_legacy_evidence")
                if table == "raw_captures":
                    _require(type(row["byte_count"]) is int and row["byte_count"] == len(raw), "vehicle_binary_invalid_legacy_evidence")
                query = query_rows[row["query_id"]]
                _require(query["source_id"] == row["source_id"] and query["query_key"] == row["query_key"],
                         "vehicle_binary_invalid_legacy_evidence")
        for row in [*snapshots.values(), *quarantines.values()]:
            body = row["body"]
            _require(row.get("body_encoding", "utf-8") == "utf-8" and row.get("raw_capture_id") is None
                     and isinstance(body, str) and bool(body) and row["content_type"] == "application/json",
                     "vehicle_binary_invalid_legacy_evidence")
            raw = body.encode("utf-8", errors="strict")
            _require(hashlib.sha256(raw).hexdigest() == row["raw_hash"], "vehicle_binary_invalid_legacy_evidence")
        for row in quarantines.values():
            query = query_rows[row["query_id"]]
            _require(row["previous_snapshot_id"] in snapshots and _json(query["query"]) == {"vehicle_id": row["vehicle_id"]}
                     and query["query_key"] == _digest(_json(query["query"])), "vehicle_binary_invalid_legacy_evidence")
        for row in _records(connection, "vehicle_verifications"):
            snapshot, query = snapshots[row["snapshot_id"]], query_rows[row["query_id"]]
            _require(row["vehicle_id"] == snapshot["vehicle_id"] and query["source_id"] == snapshot["source_id"]
                     and _json(query["query"]) == {"vehicle_id": snapshot["vehicle_id"]}
                     and query["query_key"] == _digest(_json(query["query"])), "vehicle_binary_invalid_legacy_evidence")
        if {"capture_objects", "evidence_objects"} <= tables:
            evidence = {row["raw_hash"]: row for row in _records(connection, "evidence_objects")}
            for row in _records(connection, "capture_objects"):
                capture, item = captures[row["capture_id"]], evidence[row["raw_hash"]]
                _require(capture["raw_hash"] == item["raw_hash"] and capture["byte_count"] == item["byte_count"],
                         "vehicle_binary_invalid_legacy_evidence")
        def vehicle_reference(value):
            _require(isinstance(value, str) and value in snapshots, "vehicle_binary_invalid_legacy_evidence")
        if "quarantine_reviews" in tables:
            accepted = set(quarantines)
            for other in ("source_quarantines", "rejected_observations"):
                if other in tables:
                    accepted.update(row["id"] for row in _records(connection, other))
            for row in _records(connection, "quarantine_reviews"):
                _require(row["quarantine_id"] in accepted, "vehicle_binary_invalid_legacy_evidence")
        if "garage_revisions" in tables:
            for row in _records(connection, "garage_revisions"):
                reference = _json(row["fitment_reference"])
                if reference:
                    vehicle_reference(reference["snapshot_id"])
        if "fitment_relation_revisions" in tables:
            for row in _records(connection, "fitment_relation_revisions"):
                selected, evidence = _json(row["selection"]), _json(row["vehicle_evidence"])
                vehicle_reference(selected["vehicle_snapshot_id"])
                _require(evidence["provenance"]["snapshot_id"] == selected["vehicle_snapshot_id"],
                         "vehicle_binary_invalid_legacy_evidence")
                _require(_digest(_json(row["binding"])) == row["binding_hash"], "vehicle_binary_invalid_legacy_evidence")
        if "reparse_runs" in tables:
            for row in _records(connection, "reparse_runs"):
                values = {key: _json(row[key]) for key in ("input", "parser", "baseline")}
                _require(_digest(values) == row["input_hash"], "vehicle_binary_invalid_legacy_evidence")
                if values["input"]["target_kind"] == "vehicle" and values["baseline"]:
                    vehicle_reference(values["baseline"]["snapshot_id"])
        if "parser_evaluations" in tables:
            for row in _records(connection, "parser_evaluations"):
                bindings = _json(row["bindings"])
                values = {key: row[key] for key in ("source_id", "target_bundle_id", "control_bundle_id", "deployment_revision")}
                _require(_digest({**values, "bindings": bindings}) == row["input_hash"], "vehicle_binary_invalid_legacy_evidence")
                for binding in bindings:
                    if binding["input"]["target_kind"] == "vehicle" and binding.get("reference"):
                        vehicle_reference(binding["reference"]["snapshot_id"])
        if "interest_events" in tables:
            for row in _records(connection, "interest_events"):
                payload = _json(row["payload"])
                _require(payload["event_hash"] == row["event_hash"] == _digest({key: value for key, value in payload.items()
                         if key != "event_hash"}), "vehicle_binary_invalid_legacy_evidence")
                if row["domain"] == "vehicle":
                    vehicle_reference(row["origin_id"])
                for reference in payload.get("evidence", []):
                    if reference.get("kind") == "vehicle_snapshot":
                        vehicle_reference(reference["snapshot_id"])
        if "offline_pack_plans" in tables:
            for row in _records(connection, "offline_pack_plans"):
                for item in _json(row["preview"]).get("resolved", []):
                    if item["reference"]["kind"] == "vehicle":
                        vehicle_reference(item["reference"]["snapshot_id"])
    except VehicleBinaryMigrationError:
        raise
    except Exception:
        raise VehicleBinaryMigrationError("vehicle_binary_invalid_legacy_evidence") from None


def _integrity(connection):
    _require(_rows(connection, "PRAGMA integrity_check") == [("ok",)]
             and _rows(connection, "PRAGMA foreign_key_check") == [], "vehicle_binary_integrity_failed")


def _snapshot(connection):
    schema = _sqlite_objects(connection)
    tables = {}
    for kind, table in schema:
        if kind != "table":
            continue
        columns = [row[1] for row in _rows(connection, "PRAGMA table_xinfo(" + _quote(table) + ")") if row[6] != 1]
        values = _rows(connection, "SELECT " + ",".join(map(_quote, columns)) + " FROM " + _quote(table))
        tables[table] = {"columns": columns, "rows": sorted(values, key=repr),
                         "foreign_keys": sorted(_rows(connection, "PRAGMA foreign_key_list(" + _quote(table) + ")"), key=repr)}
    return {"schema": schema, "tables": tables}


def _preserved(connection, before, *, schema_delta=False, allow_version_additions=False):
    actual_schema = _sqlite_objects(connection)
    for table, expected in before["tables"].items():
        values = _rows(connection, "SELECT " + ",".join(map(_quote, expected["columns"])) + " FROM " + _quote(table))
        actual = sorted(values, key=repr)
        if table == "tire_schema_versions" and allow_version_additions:
            _require(all(row in actual for row in expected["rows"]), "vehicle_binary_preservation_failed")
        else:
            _require(actual == expected["rows"], "vehicle_binary_preservation_failed")
        foreign_keys = sorted(_rows(connection, "PRAGMA foreign_key_list(" + _quote(table) + ")"), key=repr)
        # SQLite renumbers FK identifiers when a constraint is appended. The
        # relationship tuple, including composite sequence/order, must survive.
        old_fk = [row[1:] for row in expected["foreign_keys"]]
        new_fk = [row[1:] for row in foreign_keys]
        _require(all(row in new_fk for row in old_fk), "vehicle_binary_preservation_failed")
    if schema_delta:
        for key, value in before["schema"].items():
            if key[0] == "table" and key[1] in TARGET_TABLES:
                continue
            _require(actual_schema.get(key) == value, "vehicle_binary_preservation_failed")


def _create_vehicle_sql(table, original_sql):
    opening = original_sql.find("(")
    closing = _closing_paren(original_sql, opening)
    inner = original_sql[opening + 1:closing]
    # SQLite requires every column definition before table constraints. Split
    # only outer commas; quoted literals/identifiers, comments and nested CHECK
    # expressions cannot introduce a false column or constraint boundary.
    masked = _sql_code_mask(inner, mask_identifiers=True)
    parts, depth, start = [], 0, 0
    for index, character in enumerate(masked):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            _require(depth >= 0)
        elif character == "," and depth == 0:
            parts.append(inner[start:index])
            start = index + 1
    _require(depth == 0)
    parts.append(inner[start:])
    def table_constraint(part):
        return re.match(r"\s*(?:CONSTRAINT|PRIMARY|UNIQUE|CHECK|FOREIGN)\b",
                        _sql_code_mask(part, mask_identifiers=True), re.IGNORECASE) is not None
    boundary = next((index for index, part in enumerate(parts) if table_constraint(part)), len(parts))
    _require(all(table_constraint(part) for part in parts[boundary:]))
    body_count = 0
    for index in range(boundary):
        match = re.match(r'^\s*(?:body|"body"|\[body\]|`body`)\s+TEXT\s+(?P<not_null>NOT\s+NULL)\b',
                         _sql_code_mask(parts[index]), re.IGNORECASE)
        if match:
            first, last = match.span("not_null")
            parts[index] = parts[index][:first] + parts[index][last:]
            body_count += 1
    _require(body_count == 1)
    columns = ["\n\tbody_encoding VARCHAR(16) NOT NULL DEFAULT 'utf-8'", "\n\traw_capture_id VARCHAR(64)"]
    constraints = ["\n\tFOREIGN KEY(raw_capture_id) REFERENCES raw_captures (id) ON DELETE RESTRICT"]
    constraints.extend("\n\tCONSTRAINT " + _quote(name) + " CHECK (" + value + ")" for name, value in _checks_for(table).items())
    definitions = ",".join([*parts[:boundary], *columns, *parts[boundary:], *constraints])
    return "CREATE TABLE " + _quote("__vehicle_binary_024_" + table) + " (" + definitions + ")" + original_sql[closing + 1:]


def _dependent_objects(schema):
    referenced = set(VEHICLE_TABLES)
    views = {}
    changed = True
    def mentions(sql, names):
        return any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", sql or "", re.IGNORECASE)
                   for name in names)
    while changed:
        changed = False
        for (kind, name), (_, sql) in schema.items():
            if kind == "view" and name not in views and mentions(sql, referenced):
                views[name] = sql
                referenced.add(name)
                changed = True
    triggers = {name: sql for (kind, name), (table, sql) in schema.items()
                if kind == "trigger" and (table in VEHICLE_TABLES or mentions(sql, referenced))}
    indexes = {name: sql for (kind, name), (table, sql) in schema.items()
               if kind == "index" and table in VEHICLE_TABLES and sql is not None}
    return views, triggers, indexes


def _register_models():
    # Same explicit model closure as the 023 source, without importing main.
    modules = ("ai_models", "ai_stream_models", "candidate_ai_models", "device_ai_models", "embedding_models",
        "external_api_models", "fitment_relation_models", "golden_models", "identity_contract_models", "identity_models",
        "interest_applicability_models", "interest_catalog_models", "interest_models", "knowledge_models", "monitor_task_models",
        "offline_models", "parser_release_models", "query_fallback_policies", "recall_discovery", "recall_discovery_monitor_models",
        "recall_models", "reparse_models", "report_models", "source_material_models", "source_setting_models", "test_events",
        "test_sku_link_models", "vehicles", "webhook_models")
    for module in modules:
        importlib.import_module("tire_api." + module)


def migrate_sqlite(engine, *, failure_hook=None):
    """Explicit managed upgrade, including older additive steps, on one connection.

The caller must preserve DB/object/bundle assets before invoking this private
rehearsal. External asset files are not opened or changed by this function.
"""
    _require(engine.dialect.name == "sqlite", "vehicle_binary_unsupported_backend")
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        _require(isinstance(raw, sqlite3.Connection) and not raw.in_transaction, "vehicle_binary_transaction_active")
        success = False
        try:
            state = schema_state(connection)
            if state == "current":
                _require(VERSION in {row[0] for row in _rows(connection, "SELECT version FROM tire_schema_versions")},
                         "vehicle_binary_migration_required")
                _integrity(connection)
                tables = sum(kind == "table" for kind, _ in _sqlite_objects(connection))
                connection.commit()
                success = True
                return {"version": VERSION, "changed_tables": 0, "preserved_original_tables": tables,
                        "already_current": True, "object_bundle_entity_audit": "not_performed", "normal_upgrade_ready": False}
            _require(state == "legacy", "vehicle_binary_schema_inconsistent")
            connection.commit()  # End SQLAlchemy's read-only autobegin before PRAGMA.
            _execute(raw, "PRAGMA foreign_keys=OFF")
            _require(_rows(raw, "PRAGMA foreign_keys") == [(0,)], "vehicle_binary_foreign_keys_not_disabled")
            _execute(raw, "BEGIN IMMEDIATE")
            _require(schema_state(connection) == "legacy")
            _required_relationships(connection)
            _integrity(connection)
            _validate_evidence(connection)
            original = _snapshot(connection)
            _register_models()
            from .db import Base
            from .migrations import upgrade
            _require(all(name in Base.metadata.tables for name in PRIOR_MODEL_TABLES))
            Base.metadata.create_all(connection, tables=[Base.metadata.tables[name] for name in PRIOR_MODEL_TABLES
                                                        if name not in TARGET_TABLES])
            upgrade(connection, include_vehicle_binary=False)
            _require(PRIOR_VERSION in {row[0] for row in _rows(connection, "SELECT version FROM tire_schema_versions")}
                     and schema_state(connection) == "legacy")
            _preserved(connection, original, allow_version_additions=True)
            before = _snapshot(connection)
            for table in RAW_TABLES:
                constraints = " ".join("CONSTRAINT " + _quote(name) + " CHECK (" + value + ")"
                                       for name, value in _checks_for(table).items())
                _execute(connection, "ALTER TABLE " + _quote(table)
                         + " ADD COLUMN body_encoding VARCHAR(16) NOT NULL DEFAULT 'utf-8' " + constraints)
            for table in VEHICLE_TABLES:
                temporary = "__vehicle_binary_024_" + table
                _require(("table", temporary) not in before["schema"])
                _execute(connection, _create_vehicle_sql(table, before["schema"][("table", table)][1]))
                columns = ",".join(map(_quote, before["tables"][table]["columns"]))
                _execute(connection, "INSERT INTO " + _quote(temporary) + " (" + columns + ") SELECT " + columns + " FROM " + _quote(table))
                _require(_rows(connection, "SELECT " + columns + " FROM " + _quote(temporary))
                         == _rows(connection, "SELECT " + columns + " FROM " + _quote(table)), "vehicle_binary_preservation_failed")
            if failure_hook:
                failure_hook("after_copy")
            views, triggers, indexes = _dependent_objects(before["schema"])
            for name in triggers:
                _execute(connection, "DROP TRIGGER " + _quote(name))
            for name in views:
                _execute(connection, "DROP VIEW " + _quote(name))
            for table in reversed(VEHICLE_TABLES):
                _execute(connection, "DROP TABLE " + _quote(table))
            for table in VEHICLE_TABLES:
                _execute(connection, "ALTER TABLE " + _quote("__vehicle_binary_024_" + table) + " RENAME TO " + _quote(table))
            for sql in [*indexes.values(), *views.values(), *triggers.values()]:
                _execute(connection, sql)
            for table in VEHICLE_TABLES:
                _execute(connection, "CREATE INDEX " + _quote("ix_" + table + "_raw_capture_id")
                         + " ON " + _quote(table) + " (raw_capture_id)")
            if failure_hook:
                failure_hook("after_replace")
            require_current(connection)
            _validate_evidence(connection)
            _integrity(connection)
            _preserved(connection, before, schema_delta=True)
            if failure_hook:
                failure_hook("before_version")
            connection.execute(text("INSERT INTO tire_schema_versions (version) VALUES (:version)"), {"version": VERSION})
            _preserved(connection, original, allow_version_additions=True)
            if failure_hook:
                failure_hook("before_commit")
            connection.commit()
            success = True
            return {"version": VERSION, "changed_tables": 4, "preserved_original_tables": len(original["tables"]),
                    "already_current": False, "object_bundle_entity_audit": "not_performed", "normal_upgrade_ready": False}
        except VehicleBinaryMigrationError:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise VehicleBinaryMigrationError("vehicle_binary_migration_failed") from None
        finally:
            if not success:
                connection.rollback()
            try:
                _require(not raw.in_transaction, "vehicle_binary_transaction_not_closed")
                _execute(raw, "PRAGMA foreign_keys=ON")
                _require(_rows(raw, "PRAGMA foreign_keys") == [(1,)], "vehicle_binary_foreign_keys_not_restored")
            except Exception:
                connection.invalidate()
                raise VehicleBinaryMigrationError("vehicle_binary_foreign_keys_not_restored") from None


def assert_text_only_rollback(connection):
    """Gate a separately reviewed full-backup restore; never deletes binary data."""
    dialect = getattr(getattr(connection, "dialect", None), "name", "sqlite")
    _require(dialect == "sqlite", "vehicle_binary_unsupported_backend")
    for table in TARGET_TABLES:
        if "body_encoding" in _columns(connection, table):
            _require(not _rows(connection, "SELECT 1 FROM " + _quote(table) + " WHERE body_encoding != 'utf-8' LIMIT 1"),
                     "vehicle_binary_rollback_forbidden")


def private_rehearsal(database_path, backup_file, *, offline_confirmed=False):
    """Stopped-writer private rehearsal; not an online or whole-asset backup.

    Exclusive file creation prevents overwriting an existing backup. Filesystem
    path checks are not a defense against a hostile concurrent OS path swap.
    """
    from sqlalchemy import create_engine
    _require(offline_confirmed is True, "vehicle_binary_offline_confirmation_required")
    source, backup = Path(database_path).resolve(), Path(backup_file).resolve()
    _require(source.is_file() and source != backup and not backup.exists() and backup.parent.is_dir(),
             "vehicle_binary_backup_path_invalid")
    for path in (Path(database_path).absolute(), Path(backup_file).absolute()):
        for item in [*reversed(path.parents), path]:
            if item.exists():
                _require(not item.is_symlink() and not getattr(item.lstat(), "st_file_attributes", 0) & 0x400,
                         "vehicle_binary_backup_path_invalid")
    engine = create_engine("sqlite:///" + source.as_posix())
    try:
        with engine.connect() as connection:
            _require(schema_state(connection) == "legacy")
            _integrity(connection)
            _validate_evidence(connection)
            raw = connection.connection.driver_connection
            with backup.open("xb"):
                pass
            destination = sqlite3.connect(str(backup))
            try:
                raw.backup(destination)
                _integrity(destination)
            finally:
                destination.close()
        return {**migrate_sqlite(engine), "backup_requires_stopped_writers": True}
    finally:
        engine.dispose()
