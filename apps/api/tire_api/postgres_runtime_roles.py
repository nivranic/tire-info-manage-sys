"""Reviewed DML policy and effective-ACL check for the trusted application tier."""
import json
import sys

from sqlalchemy import text

from .external_fact_governance import GovernanceError
from .external_fact_governance_cli import _Parser, _password, _request
from .external_fact_governance_postgres import postgres_connect_args, postgres_engine
from .external_fact_governance_roles import _audit_sql, _identifier
from .external_fact_sql import LOCK_ROUTINES


MODEL_TABLES = tuple('''
ai_completions ai_draft_applications ai_evidence_packs ai_price_versions ai_requests
ai_stream_events ai_stream_executions alert_events alert_rule_revisions alert_rules audit_events
candidate_ai_authorizations candidate_ai_claims candidate_ai_preparations capture_objects
change_events device_ai_consent_claims device_ai_preparations document_text_chunks
document_text_indexes document_text_pages driving_preference_revisions embedding_cache
embedding_completions embedding_plans embedding_requests evidence_documents evidence_objects
external_api_key_minutes external_api_key_operations external_api_key_revocations external_api_keys
external_fact_grant_revisions external_fact_license_evidence fact_versions fallback_consents
fitment_relation_revisions fitment_relations garage_revisions garage_vehicles golden_case_reviews
golden_case_revisions golden_cases golden_set_revisions identity_revisions interest_events
interest_notifications interest_revisions interests knowledge_documents knowledge_facets
knowledge_index_state local_sessions manual_fact_revisions monitor_jobs monitor_runs
monitor_task_attempts monitor_task_events notification_deliveries offline_pack_plans offline_packs
parser_bundles parser_deployment_revisions parser_evaluation_completions parser_evaluation_reviews
parser_evaluations parser_executions parser_selections quarantine_approval_uses quarantine_reviews
query_fallback_policy_revisions query_fallback_previews query_fallback_uses query_run_owner_receipts
query_runs raw_captures recall_discovery_candidates recall_discovery_jobs
recall_discovery_notifications recall_discovery_pages recall_discovery_rule_revisions
recall_discovery_rules recall_discovery_runs recall_discovery_task_attempts
recall_discovery_task_events recall_events recall_monitor_jobs recall_monitor_rules
recall_monitor_runs recall_notifications recall_revisions recall_rule_revisions
recall_search_snapshots recall_search_verifications recall_snapshots recall_verifications
rejected_observations reparse_completions reparse_reviews reparse_runs report_exports
research_report_revisions research_reports safety_gate_alert_changes safety_gate_alert_observations
safety_gate_alert_revisions safety_gate_monitor_checks safety_gate_monitor_jobs
safety_gate_monitor_rules safety_gate_monitor_runs safety_gate_notifications
safety_gate_rule_revisions safety_gate_snapshots safety_gate_task_attempts safety_gate_task_events
safety_gate_verifications samr_recall_snapshots samr_recall_verifications
samr_notice_revisions samr_notice_observations samr_notice_changes
saved_comparison_revisions saved_comparisons snapshots
source_material_outcomes source_material_requests source_material_stops source_page_changes
source_page_notifications source_page_url_move_notifications source_page_url_moves
source_quarantines source_setting_revisions source_text_chunks source_text_indexes
test_event_golden_case_reviews test_event_golden_case_revisions test_event_golden_cases
test_event_golden_set_revisions test_event_revisions test_events test_sku_link_revisions
test_sku_links text_embedding_authorizations tire_catalog_revisions
tire_curation_applicability_events tire_variants users variant_identity_bindings
variant_identity_migration_applications variant_lifecycle_events vehicle_manufacturers
vehicle_models vehicle_quarantines vehicle_snapshots vehicle_trims vehicle_verifications
vehicle_wheel_fitments verifications watch_items webhook_attempts webhook_completions
webhook_dispatch_slots webhook_envelopes webhook_operations webhook_overflows webhook_queue
webhook_revisions webhook_statistics webhook_subscriptions webhook_target_slots
'''.split())
OPTIONAL_TABLES = ('embedding_vectors',)
READ_TABLES = (*MODEL_TABLES, 'tire_schema_versions', *OPTIONAL_TABLES)
GOVERNANCE_TABLES = ('external_fact_grant_revisions', 'external_fact_license_evidence')
APPEND_TABLES = (*(table for table in MODEL_TABLES if table not in GOVERNANCE_TABLES), *OPTIONAL_TABLES)
DELETE_TABLES = ('users', 'watch_items', 'knowledge_documents', 'knowledge_facets',
                 'source_text_chunks', 'document_text_pages', 'document_text_chunks')
UPDATE_COLUMNS = {
    'local_sessions': ('expires_at', 'user_id'),
    'users': ('username', 'display_name', 'password_hash', 'is_admin'),
    'query_runs': ('source_access_generation', 'state', 'reason'),
    'fallback_consents': ('used_at',),
    'query_fallback_previews': ('applied_at',),
    'monitor_jobs': ('next_due_at', 'lease_token', 'lease_until', 'last_finished_at'),
    'recall_monitor_jobs': ('next_due_at', 'lease_token', 'lease_until', 'last_finished_at'),
    'recall_discovery_jobs': ('next_due_at', 'lease_token', 'lease_until', 'last_finished_at'),
    'safety_gate_monitor_jobs': ('next_due_at', 'lease_token', 'lease_until', 'last_finished_at'),
    'notification_deliveries': ('read_at',),
    'recall_notifications': ('read_at',),
    'recall_discovery_notifications': ('read_at',),
    'safety_gate_notifications': ('read_at',),
    'interest_notifications': ('read_at',),
    'source_page_notifications': ('read_at',),
    'source_page_url_move_notifications': ('read_at',),
    'webhook_queue': ('state', 'attempts', 'next_attempt_at', 'completed_at', 'error_code',
                      'http_status', 'lease_token', 'lease_until'),
    'webhook_statistics': ('suppressed_count', 'last_suppressed_at'),
    'webhook_dispatch_slots': ('token', 'attempt_id', 'lease_until'),
    'webhook_target_slots': ('next_allowed_at',),
    'external_api_key_minutes': ('minute', 'requests'),
    'knowledge_documents': ('search_vector',),
    'knowledge_index_state': ('version', 'signature', 'documents', 'refreshed_at'),
    'source_text_indexes': ('extractor_version', 'raw_hash', 'text_hash', 'characters', 'chunks'),
    'source_text_chunks': ('search_vector',),
    'document_text_indexes': ('document_fingerprint', 'raw_hash', 'extractor_version', 'text_hash',
                              'status', 'page_count', 'characters', 'chunks', 'parser_receipt', 'indexed_at'),
    'document_text_chunks': ('search_vector',),
    'embedding_vectors': ('model_space', 'dimensions', 'embedding'),
}


def validate_policy():
    from .db import Base, register_schema_models
    register_schema_models()
    if set(Base.metadata.tables) != set(MODEL_TABLES):
        raise GovernanceError('postgres_runtime_policy_outdated')
    for table, columns in UPDATE_COLUMNS.items():
        if table in OPTIONAL_TABLES:
            continue
        if not set(columns) <= set(Base.metadata.tables[table].columns.keys()):
            raise GovernanceError('postgres_runtime_policy_outdated')


def audit_sql(*, require_grants):
    validate_policy()
    return _audit_sql(require_grants=require_grants, read_tables=READ_TABLES, append_tables=APPEND_TABLES,
                      column_updates=UPDATE_COLUMNS, delete_tables=DELETE_TABLES, optional_tables=OPTIONAL_TABLES,
                      routines=LOCK_ROUTINES)


def runtime_role_sql(role, database):
    role, database = _identifier(role), _identifier(database)
    def guard(required):
        query = audit_sql(require_grants=required).replace(':role', "'" + role + "'")
        return ('DO $runtime_role$ BEGIN IF EXISTS (' + query + ') THEN '
                "RAISE EXCEPTION 'postgres_runtime_role_invalid'; END IF; END $runtime_role$;")
    statements = ['BEGIN;', 'SET LOCAL search_path=pg_catalog,public;', "SET LOCAL lock_timeout='2s';",
        "SET LOCAL statement_timeout='5s';", "SET LOCAL idle_in_transaction_session_timeout='15s';",
        'SELECT pg_advisory_xact_lock(821741906);',
        "DO $runtime_role$ BEGIN IF current_database()<>'" + database + "' OR "
        "current_setting('server_version_num')::int<170000 THEN RAISE EXCEPTION 'postgres_runtime_target_invalid'; "
        'END IF; END $runtime_role$;', guard(False),
        f'GRANT CONNECT ON DATABASE "{database}" TO "{role}";',
        f'GRANT USAGE ON SCHEMA public TO "{role}";']
    for privilege, tables in (('SELECT', READ_TABLES), ('INSERT', APPEND_TABLES), ('DELETE', DELETE_TABLES)):
        required = [table for table in tables if table not in OPTIONAL_TABLES]
        statements.append('GRANT ' + privilege + ' ON ' + ','.join('public.' + table for table in required) + f' TO "{role}";')
    for table, columns in UPDATE_COLUMNS.items():
        grant = 'GRANT UPDATE (' + ','.join(columns) + ') ON public.' + table + f' TO "{role}";'
        if table in OPTIONAL_TABLES:
            grant = "DO $runtime_role$ BEGIN IF to_regclass('public." + table + "') IS NOT NULL THEN " + grant + ' END IF; END $runtime_role$;'
        statements.append(grant)
    for table in OPTIONAL_TABLES:
        statements.append("DO $runtime_role$ BEGIN IF to_regclass('public." + table + "') IS NOT NULL THEN "
            'GRANT SELECT,INSERT ON public.' + table + f' TO "{role}";' + ' END IF; END $runtime_role$;')
    for name in LOCK_ROUTINES:
        statements.append(f'GRANT EXECUTE ON FUNCTION public.{name}() TO "{role}";')
    statements.extend([guard(True), 'COMMIT;'])
    return '\n\n'.join(statements) + '\n'


def check_runtime_role(engine):
    query = audit_sql(require_grants=True)
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        connection.exec_driver_sql('SET LOCAL search_path=pg_catalog,public')
        connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        version = int(connection.exec_driver_sql("SELECT current_setting('server_version_num')").scalar())
        if version < 170000:
            violations = ['server_version_unsupported']
        else:
            role = connection.exec_driver_sql('SELECT current_user').scalar()
            violations = list(connection.execute(text(query), {'role': role}).scalars())
    return {'schema': 'postgres-runtime-role-check@1', 'ok': not violations, 'violations': violations}


def main(argv=None):
    engine = None
    try:
        parser = _Parser(description='Generate reviewed runtime grants or check the current connection role.')
        commands = parser.add_subparsers(dest='action', required=True)
        plan = commands.add_parser('plan')
        plan.add_argument('--role', required=True)
        plan.add_argument('--database', required=True)
        check = commands.add_parser('check')
        check.add_argument('--postgres-profile', required=True)
        args = parser.parse_args(argv)
        if args.action == 'plan':
            print(runtime_role_sql(args.role, args.database), end='')
            return 0
        if not sys.stdin.isatty():
            raise GovernanceError('interactive_authentication_required')
        parameters = postgres_connect_args(_request(args.postgres_profile))
        password = _password('Runtime PostgreSQL password: ')
        try:
            engine = postgres_engine(parameters, password)
        finally:
            del password
        result = check_runtime_role(engine)
    except GovernanceError as error:
        result = {'ok': False, 'code': error.code}
    except (Exception, KeyboardInterrupt):
        result = {'ok': False, 'code': 'postgres_runtime_role_check_failed'}
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                result = {'ok': False, 'code': 'postgres_runtime_role_check_failed'}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
