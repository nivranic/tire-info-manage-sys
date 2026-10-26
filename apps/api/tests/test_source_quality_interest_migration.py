"""Independent literal 029 interest slice -> 030; only fresh private SQLite files."""
import pytest
from sqlalchemy import event

from tire_api.migrations import upgrade
from test_source_page_migration import (prior as predecessor_028, predecessor_027,
                                      predecessor_026, native_029)
from version_registry import EXPECTED_SCHEMA_VERSIONS

VERSION = '030_interest_source_quality'


def state(connection):
    objects = [tuple(row) for row in connection.exec_driver_sql(
        'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name')]
    rows = {name: sorted((tuple(row) for row in connection.exec_driver_sql(
        'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
        for kind, name, _table, _sql in objects if kind == 'table'}
    return objects, rows


@pytest.fixture
def prior(predecessor_028):
    """029 interest slice with real older migration prerequisites, not a full deployed DB."""
    with predecessor_028.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        # The ordinary entrypoint always checks the earlier vehicle-binary
        # physical shape. Reuse its independent historical prerequisite fixture,
        # rather than disabling that guard or fabricating a ledger-only full DB.
        upgrade(connection, include_source_quality_interests=False, include_source_material_stops=False)
        native_029(connection)
        for statement in (
            '''CREATE TABLE interests (id VARCHAR(64) NOT NULL PRIMARY KEY,
                session_id VARCHAR(64) NOT NULL REFERENCES local_sessions(id), created_at DATETIME NOT NULL)''',
            'CREATE INDEX ix_interests_session_id ON interests(session_id)',
            '''CREATE TABLE interest_revisions (id VARCHAR(64) NOT NULL PRIMARY KEY,
                interest_id VARCHAR(64) NOT NULL REFERENCES interests(id), revision INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL, enabled BOOLEAN NOT NULL, archived BOOLEAN NOT NULL,
                conditions JSON NOT NULL, metric_keys JSON NOT NULL, changed_fields JSON NOT NULL,
                fingerprint VARCHAR(64) NOT NULL, actor_session_id VARCHAR(64) NOT NULL REFERENCES local_sessions(id),
                created_at DATETIME NOT NULL, UNIQUE(interest_id,revision))''',
            'CREATE INDEX ix_interest_revisions_interest_id ON interest_revisions(interest_id)',
            '''CREATE TABLE interest_events (id VARCHAR(64) NOT NULL PRIMARY KEY,
                domain VARCHAR(24) NOT NULL, origin_id VARCHAR(64) NOT NULL, observed_at DATETIME NOT NULL,
                event_hash VARCHAR(64) NOT NULL, payload JSON NOT NULL, UNIQUE(domain,origin_id))''',
            'CREATE INDEX ix_interest_events_domain ON interest_events(domain)',
            'CREATE INDEX ix_interest_events_observed_at ON interest_events(observed_at)',
            '''CREATE TABLE interest_notifications (id VARCHAR(64) NOT NULL PRIMARY KEY,
                session_id VARCHAR(64) NOT NULL REFERENCES local_sessions(id),
                interest_id VARCHAR(64) NOT NULL REFERENCES interests(id),
                interest_revision_id VARCHAR(64) NOT NULL REFERENCES interest_revisions(id),
                event_id VARCHAR(64) NOT NULL REFERENCES interest_events(id), match JSON NOT NULL,
                delivered_at DATETIME NOT NULL, read_at DATETIME, UNIQUE(interest_id,event_id))''',
            'CREATE INDEX ix_interest_notifications_session_id ON interest_notifications(session_id)',
            'CREATE INDEX ix_interest_notifications_interest_id ON interest_notifications(interest_id)',
            'CREATE INDEX ix_interest_notifications_event_id ON interest_notifications(event_id)',
        ):
            connection.exec_driver_sql(statement)
        assert connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all() == EXPECTED_SCHEMA_VERSIONS[:29]
        connection.exec_driver_sql('INSERT INTO local_sessions(id,created_at,expires_at,user_id) VALUES (?,?,?,?)',
            ('prior-029-session', '2026-01-01 00:00:00.000000', '2027-01-01 00:00:00.000000', None))
        connection.exec_driver_sql("INSERT INTO interests VALUES ('prior-029-interest','prior-029-session','2026-01-01 00:00:00.000001')")
        connection.exec_driver_sql('INSERT INTO interest_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            ('prior-029-revision', 'prior-029-interest', 1, '旧关注原字节', 1, 0,
             '[ { "kind": "brand", "values": ["synthetic"] } ]', '[]', '[ "facts.utqg_treadwear" ]',
             'a' * 64, 'prior-029-session', '2026-01-01 00:00:00.000002'))
        connection.exec_driver_sql('INSERT INTO interest_events VALUES (?,?,?,?,?,?)',
            ('b' * 64, 'tire', 'prior-029-origin', '2026-01-01 00:00:00.000003', 'c' * 64,
             '{ "schema": "interest-event@1", "label": "旧事件" }'))
        connection.exec_driver_sql('INSERT INTO interest_notifications VALUES (?,?,?,?,?,?,?,?)',
            ('prior-029-notice', 'prior-029-session', 'prior-029-interest', 'prior-029-revision', 'b' * 64,
             '{ "policy_version": "explicit-interest@1", "state": "matched" }',
             '2026-01-01 00:00:00.000004', None))
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert 'source_quality_notifications' not in {row[1] for row in connection.exec_driver_sql(
            'PRAGMA table_info(interest_revisions)')}
    return predecessor_028


def test_029_to_030_only_appends_false_column_and_ledger_preserving_old_rows(prior):
    with prior.connect() as connection:
        before_objects, before_rows = state(connection)
        before_columns = [tuple(row) for row in connection.exec_driver_sql('PRAGMA table_info(interest_revisions)')]
        before_bytes = tuple(connection.exec_driver_sql('SELECT CAST(conditions AS BLOB),CAST(metric_keys AS BLOB),'
            'CAST(changed_fields AS BLOB),CAST(fingerprint AS BLOB),CAST(name AS BLOB) FROM interest_revisions').one())
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_material_stops=False)
    with prior.connect() as connection:
        after_objects, after_rows = state(connection)
        columns = [tuple(row) for row in connection.exec_driver_sql('PRAGMA table_info(interest_revisions)')]
        assert columns[:-1] == before_columns
        assert columns[-1][1:4] == ('source_quality_notifications', 'BOOLEAN', 1)
        assert str(columns[-1][4]).strip("'()") in {'0', 'false', 'FALSE'}
        assert connection.exec_driver_sql('SELECT source_quality_notifications FROM interest_revisions').all() == [(0,)]
        assert tuple(connection.exec_driver_sql('SELECT CAST(conditions AS BLOB),CAST(metric_keys AS BLOB),'
            'CAST(changed_fields AS BLOB),CAST(fingerprint AS BLOB),CAST(name AS BLOB) FROM interest_revisions').one()) == before_bytes
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    assert {name for _kind, name, _table, _sql in after_objects} == {name for _kind, name, _table, _sql in before_objects}
    assert [row for row in after_objects if row[1] != 'interest_revisions'] == [
        row for row in before_objects if row[1] != 'interest_revisions']
    for table, values in before_rows.items():
        expected = (sorted([*values, (VERSION,)], key=repr) if table == 'tire_schema_versions'
                    else [(*row, 0) for row in values] if table == 'interest_revisions' else values)
        assert after_rows[table] == expected
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_material_stops=False)
    with prior.connect() as connection:
        assert state(connection) == (after_objects, after_rows)


def test_030_ledger_failure_rolls_back_the_new_column_and_preserves_all_old_objects(prior):
    with prior.connect() as connection:
        before = state(connection)
    reached = []
    def fail(connection, _cursor, statement, _parameters, context, _many):
        if (statement.lstrip().upper().startswith('INSERT INTO TIRE_SCHEMA_VERSIONS')
                and any(row.get('version') == VERSION for row in context.compiled_parameters or ())):
            assert 'source_quality_notifications' in {row[1] for row in connection.exec_driver_sql(
                'PRAGMA table_info(interest_revisions)')}
            reached.append(True)
            raise RuntimeError('synthetic-030-ledger-failure')
    event.listen(prior, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='^synthetic-030-ledger-failure$'):
            with prior.begin() as connection:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                upgrade(connection, include_source_material_stops=False)
    finally:
        event.remove(prior, 'before_cursor_execute', fail)
    assert reached == [True]
    with prior.connect() as connection:
        assert state(connection) == before
