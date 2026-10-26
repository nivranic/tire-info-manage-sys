"""Read-only milestone observations and independently declared migration deltas.

The existing fixtures use current table shapes with a historical version ledger;
they are not copies of a complete historical database. Observe the real version
INSERT on its own connection, then let the production upgrade finish normally.
No future version is seeded, no branch is skipped, and no expected DDL is learned
from the upgraded database or imported from product trigger generators.
"""
import re

from sqlalchemy import event, inspect, text

from version_registry import EXPECTED_SCHEMA_VERSIONS


# Fixed review contract for 013, 019-023 and 025-026, plus every later additive
# guard family (through 032) that milestone predecessors already build via
# create_all on current shapes. These declarations are test-owned,
# including exact conflict predicates and failure policies, not product outputs.
_TRIGGER_CONTRACT = {
    'device_ai_preparations': ('device', 'FAIL', 'device_ai_ledger_immutable',
        'id = NEW.id OR (actor_session_id = NEW.actor_session_id AND idempotency_key = NEW.idempotency_key)'
        ' OR (actor_session_id = NEW.actor_session_id AND host_receipt_id = NEW.host_receipt_id)'
        ' OR (actor_session_id = NEW.actor_session_id AND intent_id = NEW.intent_id) OR ai_pack_id = NEW.ai_pack_id'),
    'device_ai_consent_claims': ('device', 'FAIL', 'device_ai_ledger_immutable',
        'id = NEW.id OR (actor_session_id = NEW.actor_session_id AND analysis_key = NEW.analysis_key)'
        ' OR preparation_id = NEW.preparation_id OR ai_request_id = NEW.ai_request_id'),
    'test_sku_links': ('after_create', 'FAIL', 'test_sku_link_immutable',
        'id = NEW.id OR (event_id = NEW.event_id AND participant_key = NEW.participant_key)'),
    'test_sku_link_revisions': ('after_create', 'FAIL', 'test_sku_link_immutable',
        'id = NEW.id OR (link_id = NEW.link_id AND revision = NEW.revision)'
        ' OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
    'source_material_requests': ('after_create', 'FAIL', 'source_material_immutable',
        'id = NEW.id OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
    'source_material_outcomes': ('after_create', 'FAIL', 'source_material_immutable',
        'request_id = NEW.request_id OR (document_id IS NOT NULL AND document_id = NEW.document_id)'),
    'source_material_stops': ('after_create', 'FAIL', 'source_material_immutable',
        'request_id = NEW.request_id'),
    'candidate_ai_authorizations': ('candidate', 'ABORT', 'candidate_ai_history_immutable',
        'id = NEW.id OR (scope_hash = NEW.scope_hash AND revision = NEW.revision)'),
    'candidate_ai_preparations': ('candidate', 'ABORT', 'candidate_ai_history_immutable',
        'id = NEW.id OR (pack_id = NEW.pack_id)'),
    'candidate_ai_claims': ('candidate', 'ABORT', 'candidate_ai_history_immutable',
        'id = NEW.id OR (preparation_id = NEW.preparation_id OR request_id = NEW.request_id)'),
    'webhook_subscriptions': ('after_create', 'ABORT', 'webhook_history_immutable', 'id = NEW.id'),
    'webhook_revisions': ('after_create', 'ABORT', 'webhook_history_immutable',
        'id = NEW.id OR (subscription_id = NEW.subscription_id AND revision = NEW.revision)'),
    'webhook_envelopes': ('after_create', 'ABORT', 'webhook_history_immutable',
        'id = NEW.id OR (subscription_id = NEW.subscription_id AND channel = NEW.channel AND notification_id = NEW.notification_id)'),
    'webhook_attempts': ('after_create', 'ABORT', 'webhook_history_immutable',
        'id = NEW.id OR token = NEW.token OR (envelope_id = NEW.envelope_id AND number = NEW.number)'),
    'webhook_completions': ('after_create', 'ABORT', 'webhook_history_immutable', 'attempt_id = NEW.attempt_id'),
    'webhook_operations': ('after_create', 'ABORT', 'webhook_history_immutable',
        'id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key)'),
    'webhook_overflows': ('after_create', 'ABORT', 'webhook_history_immutable', 'revision_id = NEW.revision_id'),
    'external_api_keys': ('after_create', 'ABORT', 'external_key_history_immutable', 'id = NEW.id OR bearer_sha256 = NEW.bearer_sha256'),
    'external_api_key_revocations': ('after_create', 'ABORT', 'external_key_history_immutable', 'key_id = NEW.key_id'),
    'external_api_key_operations': ('after_create', 'ABORT', 'external_key_history_immutable',
        'id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key)'),
    'external_fact_license_evidence': ('after_create', 'FAIL', 'external_fact_immutable', 'raw_hash = NEW.raw_hash'),
    'external_fact_grant_revisions': ('after_create', 'FAIL', 'external_fact_immutable',
        'id = NEW.id OR (grant_id = NEW.grant_id AND revision = NEW.revision)'
        ' OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'
        ' OR audit_event_id = NEW.audit_event_id'),
    'query_run_owner_receipts': ('after_create', 'FAIL', 'query_owner_immutable',
        'query_id = NEW.query_id OR audit_event_id = NEW.audit_event_id'),
    # Later additive families: milestone predecessors build current table shapes, so
    # their create-time guards are part of every frozen before-state. Notification
    # tables use the 'notification' style: updates may only touch read_at.
    'ai_price_versions': ('after_create', 'FAIL', 'ai_price_version_immutable',
        'id = NEW.id OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
    'test_event_golden_cases': ('after_create', 'FAIL', 'test_event_golden_immutable', 'id = NEW.id'),
    'test_event_golden_case_revisions': ('after_create', 'FAIL', 'test_event_golden_immutable',
        'id = NEW.id OR (case_id = NEW.case_id AND revision = NEW.revision)'
        ' OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
    'test_event_golden_case_reviews': ('after_create', 'FAIL', 'test_event_golden_immutable',
        'id = NEW.id OR (case_id = NEW.case_id AND revision = NEW.revision)'
        ' OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
    'test_event_golden_set_revisions': ('after_create', 'FAIL', 'test_event_golden_immutable',
        'id = NEW.id OR (set_id = NEW.set_id AND revision = NEW.revision)'
        ' OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
    'source_page_changes': ('after_create', 'FAIL', 'source_page_history_immutable',
        'id = NEW.id OR verification_id = NEW.verification_id'),
    'source_page_notifications': ('after_create', 'FAIL', 'source_page_notification_immutable',
        'id = NEW.id OR (rule_id = NEW.rule_id AND event_id = NEW.event_id)', 'notification'),
    'source_page_url_moves': ('after_create', 'FAIL', 'source_page_url_history_immutable',
        'id = NEW.id OR verification_id = NEW.verification_id'),
    'source_page_url_move_notifications': ('after_create', 'FAIL', 'source_page_url_notification_immutable',
        'id = NEW.id OR (rule_id = NEW.rule_id AND event_id = NEW.event_id)', 'notification'),
}

# Fixed columns of delivery-notification rows; only read_at may ever change.
NOTIFICATION_FIXED_COLUMNS = ('id', 'rule_id', 'rule_revision_id', 'event_id', 'delivered_at', 'fingerprint')


def snapshot_connection(connection):
    """SELECT/inspection only, on the caller's existing transaction."""
    schema = connection.exec_driver_sql(
        'SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name').all()
    tables = set(inspect(connection).get_table_names())
    rows = {name: sorted(repr(tuple(row)) for row in connection.exec_driver_sql(
        'SELECT * FROM "' + name.replace('"', '""') + '"')) for name in tables}
    return {'schema': [tuple(row) for row in schema], 'tables': tables, 'rows': rows}


def initialize_observing_version(database, version):
    """Observe exactly one real successful INSERT; never interrupt the upgrade."""
    observed = []
    reading = False

    def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        nonlocal reading
        if reading or not statement.lstrip().upper().startswith('INSERT INTO TIRE_SCHEMA_VERSIONS '):
            return
        bound = context.compiled_parameters
        if len(bound) != 1 or bound[0].get('version') != version:
            return
        assert not executemany and cursor.rowcount == 1
        assert connection.engine is database.engine and connection.in_transaction()
        # Set this before every nested SELECT/PRAGMA, so observation cannot
        # recurse or produce a second milestone while reading the same INSERT.
        reading = True
        try:
            versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
            assert versions == set(EXPECTED_SCHEMA_VERSIONS[:EXPECTED_SCHEMA_VERSIONS.index(version) + 1])
            observed.append(snapshot_connection(connection))
        finally:
            reading = False

    event.listen(database.engine, 'after_cursor_execute', after_cursor_execute)
    try:
        database.initialize()
    finally:
        event.remove(database.engine, 'after_cursor_execute', after_cursor_execute)
    assert len(observed) == 1, 'The actual target version INSERT must be observed exactly once'
    return observed[0]


def _triggers(state):
    if 'triggers' in state:
        return state['triggers']
    return {row[1]: row[3] for row in state['schema'] if row[0] == 'trigger'}


def separate_triggers(state):
    return {**state, 'schema': [row for row in state['schema'] if row[0] != 'trigger'],
            'triggers': _triggers(state)}


def assert_trigger_contract(state, *, device, candidate):
    """Exact independent names, owning tables, actions and immutable predicates."""
    groups = {'after_create'} | ({'device'} if device else set()) | ({'candidate'} if candidate else set())
    expected = {}
    for table, contract in _TRIGGER_CONTRACT.items():
        group, failure, reason, predicate = contract[:4]
        if group not in groups:
            continue
        if len(contract) > 4:  # delivery-notification style: read-only update instead of immutability
            name = table + '_read_only_update'
            expected[name] = (f'CREATE TRIGGER {name} BEFORE UPDATE ON {table} WHEN '
                + ' OR '.join(f'NEW.{column} IS NOT OLD.{column}' for column in NOTIFICATION_FIXED_COLUMNS)
                + f" BEGIN SELECT RAISE({failure}, '{reason}'); END")
            actions = ('delete',)
        else:
            actions = ('update', 'delete')
        for action in actions:
            name = f'{table}_no_{action}'
            expected[name] = (f'CREATE TRIGGER {name} BEFORE {action.upper()} ON {table} '
                              f"BEGIN SELECT RAISE({failure}, '{reason}'); END")
        name = table + '_no_replace'
        expected[name] = (f'CREATE TRIGGER {name} BEFORE INSERT ON {table} '
            f'WHEN EXISTS (SELECT 1 FROM {table} WHERE {predicate}) '
            f"BEGIN SELECT RAISE({failure}, '{reason}'); END")
    actual = _triggers(state)
    assert set(actual) == set(expected)

    def canonical(sql):
        # SQL keywords/formatting are case-insensitive; RAISE reason literals
        # are part of the contract and must retain exact spelling and spaces.
        pieces = re.split(r"('(?:''|[^'])*')", sql)
        return ''.join(piece if index % 2 else re.sub(r'\s+', '', piece).upper().replace('IFNOTEXISTS', '')
                       for index, piece in enumerate(pieces))

    for name, sql in expected.items():
        assert canonical(actual[name]) == canonical(sql), name


def assert_target_delta(before, stage, new_tables):
    """The target milestone adds only its tables and one actual version row."""
    assert stage['tables'] - before['tables'] == set(new_tables)
    assert not before['tables'] - stage['tables']
    assert [row for row in stage['schema'] if row[2] in before['tables']] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert stage['rows'][table] == before['rows'][table], table
    assert len(stage['rows']['tire_schema_versions']) == len(before['rows']['tire_schema_versions']) + 1
    assert set(before['rows']['tire_schema_versions']) < set(stage['rows']['tire_schema_versions'])
    assert all(stage['rows'][table] == [] for table in new_tables)


def assert_full_chain_preserved(before, after):
    """Later trigger deltas are fixed above; arbitrary DDL or row drift fails."""
    assert not before['tables'] - after['tables']
    old_schema = [row for row in before['schema'] if row[0] != 'trigger']
    new_schema = [row for row in after['schema'] if row[0] != 'trigger' and row[2] in before['tables']]
    assert new_schema == old_schema
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    original_triggers, final_triggers = _triggers(before), _triggers(after)
    assert all(final_triggers.get(name) == sql for name, sql in original_triggers.items())
    assert_trigger_contract(after, device=True, candidate=True)
