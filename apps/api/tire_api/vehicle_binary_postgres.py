"""Explicit PostgreSQL maintenance transaction for text-only vehicle predecessors."""
import hashlib
import json

from sqlalchemy import inspect, text

from . import vehicle_binary_migration as migration
from .postgres_schema import capture_schema

PRIOR_VERSIONS = (
    '001_verification_validators',
    '002_monitor_rule_conditions',
    '003_parser_release_provenance',
    '004_query_selection_filters',
    '005_variant_identity_contract',
    '006_source_settings',
    '007_monitor_tasks',
    '008_recall_discovery_monitoring',
    '009_ai_streaming',
    '010_offline_packs',
    '011_query_fallback_policies',
    '012_device_ai_preparations',
    '013_device_ai_ledger_triggers',
    '014_local_sessions_user',
    '015_local_sessions_user_index',
    '016_private_interests',
    '017_interest_governance_catalog',
    '018_interest_manual_applicability',
    '019_test_sku_links',
    '020_source_materials',
    '021_candidate_ai_assistance',
    '022_webhook_delivery',
    '023_external_api_keys',
)


def _row_fingerprints(connection, columns):
    fingerprints = {}
    for table, names in columns.items():
        if table == 'tire_schema_versions':
            continue
        projection = ','.join(migration._quote(name) for name in names)
        query = (f'SELECT to_jsonb(t)::text FROM (SELECT {projection} FROM public.{migration._quote(table)}) t '
                 'ORDER BY (to_jsonb(t)::text) COLLATE "C"')
        digest, count = hashlib.sha256(), 0
        with connection.execution_options(stream_results=True).exec_driver_sql(query) as rows:
            for value in rows.scalars():
                encoded = value.encode('utf-8')
                digest.update(len(encoded).to_bytes(8, 'big'))
                digest.update(encoded)
                count += 1
        connection.execution_options(stream_results=False)
        fingerprints[table] = (count, digest.hexdigest())
    return fingerprints


def _preserved_catalog(before, after, removed_not_null):
    for category, original in before.items():
        if category == 'versions':
            continue
        current = {json.dumps(row, sort_keys=True) for row in after[category]}
        for row in original:
            expected = list(row)
            if category == 'columns' and row[0] in migration.VEHICLE_TABLES and row[1] == 'body':
                expected[3] = False
            if category == 'constraints' and (row[0], row[1]) in removed_not_null:
                continue
            migration._require(json.dumps(expected, sort_keys=True) in current,
                               'vehicle_binary_preservation_failed')


def migrate_postgres(engine, *, offline_confirmed=False, backup=None, failure_hook=None):
    """Upgrade through 024 while holding write locks and preserving old values.

    The maintenance caller supplies a backup callback on the locked connection.
    API startup never calls this function. Filesystem objects and Parser bundles
    remain the responsibility of the deployment backup procedure.
    """
    migration._require(offline_confirmed is True, 'vehicle_binary_offline_confirmation_required')
    migration._require(engine.dialect.name == 'postgresql', 'vehicle_binary_unsupported_backend')
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('SET LOCAL search_path=pg_catalog,public')
            connection.exec_driver_sql("SET LOCAL lock_timeout='2s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout='30s'")
            connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout='180s'")
            connection.exec_driver_sql("SET LOCAL timezone='UTC'")
            connection.exec_driver_sql("SET LOCAL bytea_output='hex'")
            major = int(connection.exec_driver_sql("SELECT current_setting('server_version_num')").scalar())
            migration._require(major >= 170000, 'vehicle_binary_unsupported_backend')
            connection.exec_driver_sql('SELECT pg_advisory_xact_lock(821741906)')
            connection.exec_driver_sql('SELECT pg_advisory_xact_lock(821741905)')
            tables = sorted(inspect(connection).get_table_names(schema='public'))
            migration._require(bool(tables), 'vehicle_binary_schema_inconsistent')
            targets = ','.join('public.' + migration._quote(table) for table in tables)
            connection.exec_driver_sql('LOCK TABLE ' + targets + ' IN SHARE ROW EXCLUSIVE MODE')
            state = migration.schema_state(connection)
            versions = connection.exec_driver_sql('SELECT version,applied_at FROM public.tire_schema_versions ORDER BY version').all()
            if state == 'current':
                migration._require(any(row.version == migration.VERSION for row in versions),
                                   'vehicle_binary_migration_required')
                return {'version': migration.VERSION, 'already_current': True, 'changed_tables': 0,
                        'database_backup': None, 'object_bundle_entity_audit': 'not_performed'}
            migration._require(state == 'legacy', 'vehicle_binary_schema_inconsistent')
            migration._require(bool(versions) and [row.version for row in versions] == list(PRIOR_VERSIONS[:len(versions)]),
                               'vehicle_binary_schema_inconsistent')
            migration._required_relationships(connection)
            migration._validate_evidence(connection)
            original = capture_schema(connection)
            columns = {table: [column['name'] for column in inspect(connection).get_columns(table, schema='public')]
                       for table in tables}
            fingerprints = _row_fingerprints(connection, columns)
            removed_not_null = set(connection.exec_driver_sql(
                "SELECT c.relname,k.conname FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid "
                "AND a.attname='body' WHERE n.nspname='public' AND c.relname IN "
                "('vehicle_snapshots','vehicle_quarantines') AND k.contype='n' AND k.conkey=ARRAY[a.attnum]"
            ).all())
            backup_result = backup(connection) if backup is not None else None
            migration._register_models()
            from .db import Base
            from .migrations import upgrade
            connection.exec_driver_sql('SET LOCAL search_path=public,pg_catalog')
            Base.metadata.create_all(connection, tables=[Base.metadata.tables[name] for name in migration.PRIOR_MODEL_TABLES
                                                        if name not in migration.TARGET_TABLES])
            upgrade(connection, include_vehicle_binary=False)
            connection.exec_driver_sql('SET LOCAL search_path=pg_catalog,public')
            for table in migration.TARGET_TABLES:
                connection.exec_driver_sql(f'ALTER TABLE public.{migration._quote(table)} '
                                           "ADD COLUMN body_encoding VARCHAR(16) NOT NULL DEFAULT 'utf-8'")
                if table in migration.VEHICLE_TABLES:
                    connection.exec_driver_sql(f'ALTER TABLE public.{migration._quote(table)} ALTER COLUMN body DROP NOT NULL, '
                        'ADD COLUMN raw_capture_id VARCHAR(64) REFERENCES public.raw_captures(id) ON DELETE RESTRICT')
                    connection.exec_driver_sql(f'CREATE INDEX {migration._quote("ix_" + table + "_raw_capture_id")} '
                                               f'ON public.{migration._quote(table)}(raw_capture_id)')
                for name, expression in migration._checks_for(table, 'postgresql').items():
                    connection.exec_driver_sql(f'ALTER TABLE public.{migration._quote(table)} '
                                               f'ADD CONSTRAINT {migration._quote(name)} CHECK ({expression})')
                if table == migration.RAW_TABLES[0] and failure_hook is not None:
                    failure_hook('after_copy')
            if failure_hook is not None:
                failure_hook('after_replace')
            migration.require_current(connection)
            migration._validate_evidence(connection)
            migration._require(_row_fingerprints(connection, columns) == fingerprints,
                               'vehicle_binary_preservation_failed')
            _preserved_catalog(original, capture_schema(connection), removed_not_null)
            current_versions = connection.exec_driver_sql('SELECT version,applied_at FROM public.tire_schema_versions ORDER BY version').all()
            migration._require(all(row in current_versions for row in versions), 'vehicle_binary_preservation_failed')
            if failure_hook is not None:
                failure_hook('before_version')
            connection.execute(text('INSERT INTO public.tire_schema_versions(version) VALUES (:version)'),
                               {'version': migration.VERSION})
            if failure_hook is not None:
                failure_hook('before_commit')
            result = {'version': migration.VERSION, 'already_current': False, 'changed_tables': 4,
                      'preserved_original_tables': len(tables), 'preserved_original_rows': sum(value[0] for value in fingerprints.values()),
                      'database_backup': backup_result, 'object_bundle_entity_audit': 'not_performed'}
        return result
    except migration.VehicleBinaryMigrationError:
        raise
    except Exception:
        raise migration.VehicleBinaryMigrationError('vehicle_binary_migration_failed') from None
