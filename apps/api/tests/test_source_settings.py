"""Local source administration only; no source transport, Parser or model calls."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from tire_api.db import Database, QueryRun, UserSession, utcnow
from tire_api.main import create_app
from tire_api.source_setting_models import SourceSettingRevision
from tire_api.source_settings import (SourceAccessBlocked, SourceSettingDecision, SourceSettingError,
    SourceSettingPreview, append_source_setting, assert_source_access, assert_source_run_access,
    current_setting, preview_source_setting, source_setting)

SOURCE = 'michelin-us'


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv('TI_DISABLED_SOURCES', raising=False)
    app = create_app('sqlite://')
    with TestClient(app) as client:
        yield client, app.state.database


def test_complete_catalog_is_read_only_and_does_not_promote_pending_source(setup):
    client, _database = setup
    response = client.get('/v1/source-settings')
    assert response.status_code == 200
    items = {row['source_id']: row for row in response.json()['items']}
    assert len(items) == 11
    assert items['xiaomi-cn-vehicles']['target_kind'] == 'vehicle'
    assert items['nhtsa-us-recalls']['target_kind'] == 'recall'
    assert items['eprel']['registered_status'] == 'configuration_required'
    assert items['eprel']['can_fetch'] is False
    assert all(row['management']['revision'] == 0 for row in items.values())
    with _database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 0
        assert db.scalar(select(func.count()).select_from(QueryRun)) == 0


def proposed(client, action, *, source=SOURCE, **extra):
    response = client.post(f'/v1/source-settings/{source}/preview', json={'action': action, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def decision(client, action, *, source=SOURCE, **extra):
    preview = proposed(client, action, source=source, **extra)
    return {'action': action, **extra, 'expected_revision': preview['revision'],
        'expected_fingerprint': preview['fingerprint'], 'operator': 'Synthetic Operator', 'reason': 'Synthetic local decision'}


def revise(client, payload, *, source=SOURCE, key=None):
    return client.post(f'/v1/source-settings/{source}/revisions', json=payload,
                       headers={'Idempotency-Key': key or str(uuid4())})


def test_state_history_restore_paused_and_notes_generation(setup):
    client, database = setup
    edited = revise(client, decision(client, 'edit_notes', notes='synthetic note')).json()
    assert edited['source']['management']['access_generation'] == 0
    paused = revise(client, decision(client, 'pause', notes=None)).json()
    assert paused['event']['notes'] == 'synthetic note' and paused['event']['access_generation'] == 1
    assert paused['source']['effective_status'] == 'paused' and not paused['source']['can_fetch']
    archived = revise(client, decision(client, 'archive')).json()
    assert archived['event']['access_generation'] == 2
    blocked = proposed(client, 'enable')
    assert not blocked['can_submit'] and blocked['blockers'] == ['source_setting_restore_required']
    restored = revise(client, decision(client, 'restore')).json()
    assert restored['source']['management']['state'] == 'paused' and restored['event']['access_generation'] == 3
    enabled = revise(client, decision(client, 'enable')).json()
    assert enabled['source']['can_fetch'] and enabled['event']['access_generation'] == 4
    cleared = revise(client, decision(client, 'edit_notes', notes='')).json()
    assert cleared['event']['notes'] == '' and cleared['event']['access_generation'] == 4
    history = client.get(f'/v1/source-settings/{SOURCE}/history?offset=1&limit=2').json()
    assert history['total'] == 6 and [event['revision'] for event in history['items']] == [5, 4]
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(QueryRun)) == 0


def test_original_idempotent_event_is_separate_from_newer_current_projection(setup):
    client, database = setup
    payload, key = decision(client, 'pause'), str(uuid4())
    first = revise(client, payload, key=key)
    assert first.status_code == 201
    revise(client, decision(client, 'enable'))
    repeated = revise(client, payload, key=key).json()
    assert repeated['replayed'] is True and repeated['event'] == first.json()['event']
    assert repeated['event']['idempotency_key'] == key and repeated['event']['revision'] == 1
    assert repeated['source']['management']['revision'] == 2 and repeated['source']['can_fetch']
    assert revise(client, {**payload, 'reason': 'Changed payload'}, key=key).status_code == 409
    other = revise(client, payload, source='michelin-uk', key=key)
    assert other.status_code == 409 and other.json()['detail']['code'] == 'idempotency_payload_mismatch'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 2


def test_stale_revision_and_changed_environment_preview_reject_without_append(setup, monkeypatch):
    client, database = setup
    stale = decision(client, 'pause')
    revise(client, decision(client, 'edit_notes', notes='new note'))
    rejected = revise(client, stale)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'source_setting_revision_conflict'
    current = decision(client, 'pause')
    monkeypatch.setenv('TI_DISABLED_SOURCES', SOURCE)
    rejected = revise(client, current)
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'source_setting_preview_stale'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 1


@pytest.mark.parametrize('action', ['enable', 'edit_notes'])
def test_no_changes_never_appends(setup, action):
    client, database = setup
    extra = {'notes': ''} if action == 'edit_notes' else {}
    preview = proposed(client, action, **extra)
    assert not preview['can_submit'] and preview['blockers'] == ['source_setting_no_changes']
    result = revise(client, decision(client, action, **extra))
    assert result.status_code == 409 and result.json()['detail']['code'] == 'source_setting_no_changes'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 0


@pytest.mark.parametrize('payload', [
    {'action': 'edit_notes'}, {'action': 'edit_notes', 'notes': None},
    {'action': 'pause', 'notes': ''}, {'action': 'ready'},
    {'action': 'pause', 'homepage': 'https://fixture.example/elsewhere'},
    {'action': 'pause', 'source_class': 'regulatory'}, {'action': 'pause', 'adapter': 'untrusted'},
    {'action': 'edit_notes', 'notes': 'bad\x00notes'}, {'action': 'edit_notes', 'notes': 'x' * 2001},
])
def test_mutable_scope_and_notes_are_strict(setup, payload):
    client, _database = setup
    assert client.post(f'/v1/source-settings/{SOURCE}/preview', json=payload).status_code == 422


@pytest.mark.parametrize('field,value', [('operator', ''), ('operator', 'x' * 101),
    ('reason', 'four'), ('reason', 'x' * 2001), ('reason', 'bad\x01reason')])
def test_signed_changes_validate_existing_text_bounds(setup, field, value):
    client, _database = setup
    assert revise(client, {**decision(client, 'pause'), field: value}).status_code == 422


def test_unknown_source_and_invalid_uuid_do_not_create_records(setup):
    client, database = setup
    assert client.get('/v1/source-settings/not-registered').status_code == 404
    assert client.post('/v1/source-settings/not-registered/preview', json={'action': 'pause'}).status_code == 404
    assert revise(client, decision(client, 'pause'), key='not-a-uuid').status_code == 422
    assert client.get(f'/v1/source-settings/{SOURCE}/history?limit=101').status_code == 422
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 0


def test_pending_and_environment_disabled_cannot_be_promoted_by_local_enable(setup, monkeypatch):
    client, database = setup
    for source in ('eprel', SOURCE):
        assert revise(client, decision(client, 'pause', source=source), source=source).status_code == 201
    monkeypatch.setenv('TI_DISABLED_SOURCES', SOURCE)
    eprel = proposed(client, 'enable', source='eprel')
    assert eprel['can_submit'] and not eprel['effective_after']['can_fetch']
    assert eprel['effective_after']['effective_status'] == 'configuration_required'
    result = revise(client, decision(client, 'enable', source='eprel'), source='eprel').json()
    assert result['source']['management']['state'] == 'enabled' and not result['source']['can_fetch']
    result = revise(client, decision(client, 'enable')).json()
    assert result['source']['effective_status'] == 'disabled' and result['source']['environment_disabled']
    with database.sessions() as db:
        # Management is not a replacement for native environment/capability gates.
        assert assert_source_access(db, SOURCE) == 2
        assert assert_source_access(db, 'eprel') == 2


def test_parser_pause_is_displayed_but_keeps_its_independent_gate(setup, monkeypatch):
    from types import SimpleNamespace
    from tire_api import parser_releases
    client, database = setup
    original = parser_releases.current_deployment
    monkeypatch.setattr(parser_releases, 'current_deployment', lambda db, source_id:
        SimpleNamespace(revision=2, state='paused', bundle_id='a' * 64,
            descriptor={'parser_version': 'synthetic@1', 'parser_digest': 'b' * 64})
        if source_id == SOURCE else original(db, source_id))
    view = client.get(f'/v1/source-settings/{SOURCE}').json()
    assert view['registered_status'] == 'ready' and view['effective_status'] == 'parser_paused'
    assert view['blockers'] == ['parser_deployment_paused'] and view['can_fetch'] is False
    with database.sessions() as db:
        assert assert_source_access(db, SOURCE) == 0


def test_reads_and_preview_do_not_write_settings_evidence_or_fts(setup):
    from sqlalchemy import event
    client, database = setup
    client.get('/v1/source-settings')  # Acquire the normal local-session cookie first.
    statements = []
    def trace(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower().lstrip())
    event.listen(database.engine, 'before_cursor_execute', trace)
    try:
        assert client.get('/v1/source-settings').status_code == 200
        assert client.get(f'/v1/source-settings/{SOURCE}').status_code == 200
        assert client.get(f'/v1/source-settings/{SOURCE}/history').json()['items'] == []
        assert proposed(client, 'pause')['can_submit']
    finally:
        event.remove(database.engine, 'before_cursor_execute', trace)
    assert not any(statement.startswith(('insert ', 'update ', 'delete ', 'create ', 'alter ')) for statement in statements)
    assert not any('knowledge_fts' in statement or 'knowledge_documents' in statement for statement in statements)


def test_management_guards_are_read_only_preserve_notes_pin_and_reject_aba_and_null(setup):
    client, database = setup
    with database.sessions() as db:
        assert current_setting(db, 'caller-validated-synthetic-source')['access_generation'] == 0
        assert assert_source_access(db, SOURCE) == 0
    revise(client, decision(client, 'edit_notes', notes='not an access revocation'))
    with database.sessions() as db:
        db.info['source_settings_commit_count'] = 0
        from sqlalchemy import event
        def committed(_db):
            db.info['source_settings_commit_count'] += 1
        event.listen(db, 'after_commit', committed)
        assert assert_source_access(db, SOURCE, 0) == 0
        assert db.info['source_settings_commit_count'] == 0
        event.remove(db, 'after_commit', committed)
        old = QueryRun(source_id=SOURCE, source_access_generation=None)
        with pytest.raises(SourceAccessBlocked, match='source_access_pin_missing'):
            assert_source_run_access(db, old)
    revise(client, decision(client, 'pause'))
    with database.sessions() as db:
        with pytest.raises(SourceAccessBlocked, match='source_paused'):
            assert_source_access(db, SOURCE)
    revise(client, decision(client, 'enable'))
    with database.sessions() as db:
        with pytest.raises(SourceAccessBlocked, match='source_access_changed'):
            assert_source_access(db, SOURCE, 0)
        assert assert_source_access(db, SOURCE, 2) == 2


def test_legacy_sources_members_unchanged_with_effective_overlay(setup):
    client, _database = setup
    before = client.get('/v1/sources').json()['sources']
    assert 'xiaomi-cn-vehicles' not in {item['id'] for item in before}
    revise(client, decision(client, 'pause'))
    after = client.get('/v1/sources').json()['sources']
    assert [item['id'] for item in after] == [item['id'] for item in before]
    selected = next(item for item in after if item['id'] == SOURCE)
    assert selected['status'] == 'paused' and selected['source_setting']['management']['access_generation'] == 1


@pytest.mark.parametrize('operation', ['edit', 'delete'])
def test_source_history_is_immutable(setup, operation):
    client, database = setup
    revise(client, decision(client, 'pause'))
    with database.sessions() as db:
        row = db.scalar(select(SourceSettingRevision))
        if operation == 'edit':
            row.notes = 'tampered'
        else:
            db.delete(row)
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
        db.rollback()


def test_tampered_history_is_detected(setup):
    client, database = setup
    revise(client, decision(client, 'pause'))
    with database.sessions() as db:
        db.execute(update(SourceSettingRevision).values(state='enabled'))
        db.commit()
    assert client.get(f'/v1/source-settings/{SOURCE}').status_code == 503


def test_synthetic_legacy_upgrade_preserves_query_values_and_null_pin(tmp_path):
    import sqlite3
    from datetime import timedelta
    path = tmp_path / 'legacy.sqlite'
    url = 'sqlite:///' + path.as_posix()
    database = Database(url)
    database.initialize()
    with database.sessions() as db:
        db.add(UserSession(id='synthetic-legacy-session', expires_at=utcnow() + timedelta(days=1)))
        db.flush()
        db.add(QueryRun(id='synthetic-legacy-run', session_id='synthetic-legacy-session', source_id=SOURCE,
            query_key='a' * 64, query={'model': 'Synthetic Tire'}, fallback_policy='ask'))
        db.commit()
    database.close()
    with sqlite3.connect(path) as connection:
        connection.execute('ALTER TABLE query_runs DROP COLUMN source_access_generation')
        connection.execute('DROP TABLE source_setting_revisions')
        connection.execute("DELETE FROM tire_schema_versions WHERE version = '006_source_settings'")
        before = connection.execute('SELECT * FROM query_runs').fetchall()
        columns = [item[1] for item in connection.execute('PRAGMA table_info(query_runs)')]
        versions = set(row[0] for row in connection.execute('SELECT version FROM tire_schema_versions'))
    database = Database(url)
    try:
        database.initialize()
        database.initialize()
        with database.sessions() as db:
            assert db.get(QueryRun, 'synthetic-legacy-run').source_access_generation is None
            assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 0
        with sqlite3.connect(path) as connection:
            quoted = ','.join('"' + name + '"' for name in columns)
            assert connection.execute('SELECT ' + quoted + ' FROM query_runs').fetchall() == before
            assert set(row[0] for row in connection.execute('SELECT version FROM tire_schema_versions')) == versions | {'006_source_settings'}
    finally:
        database.close()


def test_independent_sqlite_connections_serialize_competing_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    url = 'sqlite:///' + (tmp_path / 'concurrent.sqlite').as_posix()
    first, second = Database(url), Database(url)
    first.initialize()
    second.initialize()
    try:
        with first.sessions() as db:
            preview = preview_source_setting(db, SOURCE, SourceSettingPreview(action='pause'))
        payload = SourceSettingDecision(action='pause', expected_revision=0,
            expected_fingerprint=preview['fingerprint'], operator='Synthetic Operator', reason='Concurrent synthetic change')
        barrier = Barrier(2)
        def submit(database, actor):
            with database.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    return append_source_setting(db, SOURCE, payload, actor, str(uuid4()))['event']['revision']
                except SourceSettingError as error:
                    return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = [executor.submit(submit, database, actor) for database, actor in
                    ((first, 'synthetic-one'), (second, 'synthetic-two'))]
            results = [job.result(timeout=30) for job in jobs]
        assert results.count(1) == 1 and results.count('source_setting_revision_conflict') == 1
        with second.sessions() as db:
            assert current_setting(db, SOURCE)['revision'] == 1
            assert db.scalar(select(func.count()).select_from(SourceSettingRevision)) == 1
    finally:
        first.close()
        second.close()
