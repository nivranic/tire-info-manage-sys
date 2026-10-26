"""Synthetic URL-move monitoring (migration 032); no real source, Provider or retained DB."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError

from tire_api.db import AlertRule, Database, MonitorJob, Verification
from tire_api.migrations import upgrade
from tire_api.service import QueryService
from tire_api.source_page_models import SourcePageChange
from tire_api.source_page_url_models import SourcePageUrlMove, SourcePageUrlMoveNotification, VERSION
from tire_api.source_page_url_monitoring import append_url_move
from test_core import QUERY, count, live, setup, success
from test_source_page_monitoring import change as page_change, create as create_page_rule
from test_source_page_monitoring import notices as page_notices
from version_registry import EXPECTED_SCHEMA_VERSIONS

OLD_URL = 'https://fixture.example/tires/product'
NEW_URL = 'https://fixture.example/tires/new-page'
BACK_URL = 'https://fixture.example/tires/legacy-page'


def create_url_rule(client, **changes):
    return client.post('/v1/alert-rules', json={'name': '合成地址迁移监控', 'source_id': 'fixture',
        'query': QUERY['query'], 'enabled': True, 'kinds': ['url_moved'],
        'fields': [], 'conditions': {}, 'variant_id': None, **changes})


def edit_rule(client, rule, **changes):
    settings = {key: rule[key] for key in ('name', 'interval_seconds', 'enabled', 'kinds', 'fields', 'conditions')}
    return client.put('/v1/alert-rules/' + rule['id'], json={**settings,
        'expected_revision': rule['revision'], **changes})


def move(client, registry, body, url):
    registry.result = success(body, url=url)
    response = live(client)
    assert response.status_code == 200 and response.json()['data_state'] == 'live', response.text
    return response.json()


def url_notices(client, **params):
    response = client.get('/v1/source-page-url-move-notifications', params={'mode': 'history', **params})
    assert response.status_code == 200, response.text
    return response.json()


def replay_move(database, event_id):
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        row = db.get(SourcePageUrlMove, event_id)
        assert append_url_move(db, db.get(Verification, row.verification_id),
                               db.get(Verification, row.previous_verification_id)).id == row.id
        db.commit()


def test_url_move_records_frozen_event_and_independent_notification(setup):
    client, registry, database = setup
    rule = create_url_rule(client).json()
    first = live(client).json()
    moved = move(client, registry, 'moved-body-B', NEW_URL)
    data = url_notices(client)
    assert data['scope'] == 'local_workspace' and data['data_state'] == 'local_snapshot'
    assert data['total'] == 1 and data['offset'] == 0 and data['limit'] == 25
    notice = data['items'][0]
    assert set(notice) == {'id', 'rule_id', 'rule_name', 'rule_revision', 'read_at', 'delivered_at', 'event'}
    assert notice['rule_id'] == rule['id'] and notice['rule_revision'] == 1 and notice['read_at'] is None
    evidence = notice['event']
    assert set(evidence) == {'id', 'kind', 'source_id', 'query', 'previous_source_url', 'source_url', 'before', 'after'}
    assert evidence['kind'] == 'url_moved' and evidence['query'] == QUERY['query']
    assert evidence['previous_source_url'] == OLD_URL and evidence['source_url'] == NEW_URL
    assert evidence['before']['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert evidence['after']['snapshot_id'] == moved['provenance'][0]['snapshot_id']
    for side, url in ((evidence['before'], OLD_URL), (evidence['after'], NEW_URL)):
        assert set(side) == {'snapshot_id', 'verification_id', 'source_url', 'observed_at', 'verified_at', 'parser_version'}
        assert side['source_url'] == url and all(value is not None for value in side.values())
    assert count(database, SourcePageChange) == 0 and page_notices(client)['total'] == 0
    detail = client.get('/v1/source-page-url-move-notifications/' + notice['id'], params={'mode': 'history'})
    assert detail.status_code == 200 and detail.json()['item'] == notice
    marked = client.put('/v1/source-page-url-move-notifications/' + notice['id'] + '/read',
                        json={'read': True}).json()
    assert marked['read_at'] and url_notices(client, unread=True)['total'] == 0
    assert client.put('/v1/source-page-url-move-notifications/' + notice['id'] + '/read',
                      json={'read': False}).json()['read_at'] is None


def test_identical_content_move_is_url_event_never_page_change(setup):
    client, registry, database = setup
    create_url_rule(client)
    create_page_rule(client)
    registry.result = success('identical-body')
    assert live(client).json()['data_state'] == 'live'
    move(client, registry, 'identical-body', NEW_URL)
    assert url_notices(client)['total'] == 1
    assert page_notices(client)['total'] == 0 and count(database, SourcePageChange) == 0


def test_move_back_records_second_independent_event(setup):
    client, registry, database = setup
    create_url_rule(client)
    live(client)
    move(client, registry, 'moved-B', NEW_URL)
    move(client, registry, 'moved-C', BACK_URL)
    data = url_notices(client)
    assert data['total'] == 2 and count(database, SourcePageUrlMove) == 2
    pairs = {(item['event']['previous_source_url'], item['event']['source_url']) for item in data['items']}
    assert pairs == {(OLD_URL, NEW_URL), (NEW_URL, BACK_URL)}


def test_page_change_after_move_uses_new_url_baseline(setup):
    client, registry, database = setup
    create_url_rule(client)
    create_page_rule(client)
    live(client)
    moved = move(client, registry, 'moved-B', NEW_URL)
    changed = page_change(client, registry, body='moved-page-C', url=NEW_URL)
    page_data = page_notices(client)
    assert page_data['total'] == 1
    assert page_data['items'][0]['event']['source_url'] == NEW_URL
    assert page_data['items'][0]['event']['before']['snapshot_id'] == moved['provenance'][0]['snapshot_id']
    assert page_data['items'][0]['event']['after']['snapshot_id'] == changed['provenance'][0]['snapshot_id']
    assert url_notices(client)['total'] == 1


def test_url_moves_never_leak_into_page_listings_and_reverse(setup):
    client, registry, _ = setup
    create_url_rule(client)
    create_page_rule(client)
    live(client)
    move(client, registry, 'moved-B', NEW_URL)
    assert page_notices(client)['total'] == 0
    assert client.get('/v1/source-page-notifications', params={'mode': 'history'}).json()['items'] == []
    page_change(client, registry, body='same-url-C', url=NEW_URL)
    assert page_notices(client)['total'] == 1
    assert url_notices(client)['total'] == 1


@pytest.mark.parametrize('values', [
    {'kinds': ['url_moved', 'facts_changed']}, {'fields': ['utqg_treadwear']},
    {'conditions': {'technology': 'Acoustic'}}, {'variant_id': 'not-a-page-identity'},
])
def test_url_rule_rejects_sku_or_mixed_conditions_before_writing(setup, values):
    client, _, database = setup
    assert create_url_rule(client, **values).status_code == 422
    assert count(database, AlertRule) == count(database, MonitorJob) == 0


def test_url_mode_cannot_be_switched_in_either_direction(setup):
    client, _, _database = setup
    url_rule = create_url_rule(client).json()
    page_rule = create_page_rule(client).json()
    assert edit_rule(client, url_rule, kinds=['facts_changed']).status_code == 422
    assert edit_rule(client, url_rule, kinds=['page_changed']).status_code == 422
    assert edit_rule(client, page_rule, kinds=['url_moved']).status_code == 422
    assert edit_rule(client, url_rule, name='仅改名可行').status_code == 200


def test_later_url_rules_only_see_later_moves_and_replays_never_backfill(setup):
    client, registry, database = setup
    first_rule = create_url_rule(client).json()
    live(client)
    move(client, registry, 'moved-B', NEW_URL)
    original = url_notices(client)['items'][0]
    later = create_url_rule(client, enabled=False, name='晚建暂停规则').json()
    replay_move(database, original['event']['id'])
    later = edit_rule(client, later, enabled=True).json()
    replay_move(database, original['event']['id'])
    move(client, registry, 'moved-C', BACK_URL)
    data = url_notices(client)
    assert data['total'] == 3
    later_items = [item for item in data['items'] if item['rule_id'] == later['id']]
    assert len(later_items) == 1 and later_items[0]['event']['source_url'] == BACK_URL
    first_rule = edit_rule(client, first_rule, enabled=False).json()
    replay_move(database, later_items[0]['event']['id'])
    assert url_notices(client)['total'] == 3


def test_url_move_history_is_immutable_at_orm_and_trigger_levels(setup):
    client, registry, database = setup
    create_url_rule(client)
    live(client)
    move(client, registry, 'moved-B', NEW_URL)
    with database.sessions() as db:
        row = db.scalars(select(SourcePageUrlMove)).first()
        row.source_url = OLD_URL
        with pytest.raises(ValueError, match='source_page_url_history_immutable'):
            db.commit()
        db.rollback()
        notice = db.scalars(select(SourcePageUrlMoveNotification)).first()
        notice.fingerprint = 'tampered'
        with pytest.raises(ValueError, match='source_page_url_notification_immutable'):
            db.commit()
        db.rollback()
        notice = db.scalars(select(SourcePageUrlMoveNotification)).first()
        from tire_api.db import utcnow
        notice.read_at = utcnow()
        db.commit()


def test_upgrade_adds_032_to_a_preexisting_database_without_it(tmp_path):
    database = Database('sqlite:///' + (tmp_path / 'pre-032.sqlite').as_posix())
    try:
        database.initialize()
        with database.engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            connection.exec_driver_sql('DROP TABLE source_page_url_move_notifications')
            connection.exec_driver_sql('DROP TABLE source_page_url_moves')
            connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version = '032_source_page_url_moves'")
        with database.engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            upgrade(connection)
            versions = set(connection.exec_driver_sql('SELECT version FROM tire_schema_versions').scalars())
            assert versions == set(EXPECTED_SCHEMA_VERSIONS)
            triggers = {row[0] for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='source_page_url_moves'")}
            assert len(triggers) == 3
    finally:
        database.close()


def test_fresh_initialize_is_idempotent_with_032_url_move_guards(tmp_path):
    database = Database('sqlite:///' + (tmp_path / 'new-032.sqlite').as_posix())
    try:
        database.initialize()
        database.initialize()
        with database.engine.connect() as connection:
            versions = connection.exec_driver_sql(
                'SELECT version FROM tire_schema_versions ORDER BY version').scalars().all()
            assert versions == EXPECTED_SCHEMA_VERSIONS
            for table in ('source_page_url_moves', 'source_page_url_move_notifications'):
                triggers = {row[0] for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=?", (table,))}
                assert len(triggers) == 3
    finally:
        database.close()


def test_sqlite_triggers_block_history_rewrites_and_duplicate_delivery():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        for table in (SourcePageUrlMove.__table__, SourcePageUrlMoveNotification.__table__):
            table.create(connection)
    with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO source_page_url_moves (id, schema_version, source_id, query_key, query, "
                "previous_verification_id, verification_id, previous_snapshot_id, snapshot_id, "
                "previous_source_url, source_url, observed_at, fingerprint) VALUES ('m1', "
                "'source-page-url-move@1', 'fixture', 'k1', '{}', 'pv1', 'v1', 'ps1', 'ss1', "
                "'https://a.example/old', 'https://a.example/new', '2026-10-26 00:00:00', 'f1')")
            with pytest.raises(DBAPIError, match='source_page_url_history_immutable'):
                connection.exec_driver_sql("UPDATE source_page_url_moves SET fingerprint = 'g'")
            with pytest.raises(DBAPIError, match='source_page_url_history_immutable'):
                connection.exec_driver_sql("DELETE FROM source_page_url_moves")
            connection.exec_driver_sql(
                "INSERT INTO source_page_url_move_notifications (id, rule_id, rule_revision_id, event_id, "
                "delivered_at, read_at, fingerprint) VALUES ('n1', 'r1', 'rr1', 'm1', "
                "'2026-10-26 00:00:01', NULL, 'nf1')")
            with pytest.raises(DBAPIError, match='source_page_url_notification_immutable'):
                connection.exec_driver_sql(
                    "INSERT INTO source_page_url_move_notifications (id, rule_id, rule_revision_id, event_id, "
                    "delivered_at, read_at, fingerprint) VALUES ('n2', 'r1', 'rr1', 'm1', "
                    "'2026-10-26 00:00:02', NULL, 'nf2')")
            connection.exec_driver_sql("UPDATE source_page_url_move_notifications SET read_at = '2026-10-26 01:00:00'")


def test_new_tables_compile_for_postgresql_without_claiming_a_live_server():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    move_ddl = str(CreateTable(SourcePageUrlMove.__table__).compile(dialect=postgresql.dialect()))
    assert 'previous_source_url TEXT NOT NULL' in move_ddl
    assert 'observed_at TIMESTAMP WITH TIME ZONE NOT NULL' in move_ddl
    assert 'CHECK (previous_source_url <> source_url)' in move_ddl
    notice_ddl = str(CreateTable(SourcePageUrlMoveNotification.__table__).compile(dialect=postgresql.dialect()))
    assert 'UNIQUE (rule_id, event_id)' in notice_ddl
    assert 'FOREIGN KEY(event_id) REFERENCES source_page_url_moves (id)' in notice_ddl
