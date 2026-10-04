"""Exact technical identity predicates and additive legacy-rule compatibility."""
from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text

from tire_api.db import AlertRule, AlertRuleRevision, AuditEvent, MonitorJob
from version_registry import EXPECTED_SCHEMA_VERSIONS
from tire_api.main import create_app
from tire_api.monitoring import RuleCreate, create_rule, matches_conditions, normalize_technology
from tire_api.service import QueryService
from test_core import FixtureRegistry, QUERY, VARIANT, live, setup, success
from test_monitoring import create, edit


def variant(code, technology=None, features=None, **facts):
    row = {**deepcopy(VARIANT), 'manufacturer_product_code': code, 'acoustic_technology': technology}
    row['facts'].update(facts)
    if features is not None:
        row['facts']['technology_features'] = features
    return row


@pytest.mark.parametrize('identity,expected', [
    ({'acoustic_technology': 'Acoustic'}, True),
    ({'acoustic_technology': '  ＡＣＯＵＳＴＩＣ  '}, True),
    ({'technology_features': ['XL', 'AcOuStIc']}, True),
    ({'acoustic_technology': 'NON Acoustic'}, False),
    ({'acoustic_technology': 'Acoustic Plus'}, False),
    ({'acoustic_technology': 'Fixture Acoustic'}, False),
    ({'acoustic_technology': None}, False),
    ({'technology_features': ['No Acoustic', None, {'name': 'Acoustic'}]}, False),
    ({'technology_features': 'Acoustic'}, False),
    ({'source_variant_name': 'Acoustic', 'description': 'Acoustic technology is available'}, False),
])
def test_technology_requires_complete_identity_value(identity, expected):
    assert matches_conditions(identity, {'technology': 'Acoustic'}) is expected
    assert matches_conditions(identity, {})
    assert matches_conditions(identity, None)  # Legacy SQL NULL means no condition.


@pytest.mark.parametrize('technology', ['PNCS', 'ContiSilent', 'Foam'])
def test_distinct_technologies_are_not_silent_acoustic_aliases(technology):
    assert matches_conditions({'technology_features': [technology.swapcase()]}, {'technology': technology})
    assert not matches_conditions({'technology_features': [technology]}, {'technology': 'Acoustic'})
    assert normalize_technology(technology) == technology.casefold()


@pytest.mark.parametrize('conditions', [
    None, [], {'marketing': 'Acoustic'}, {'technology': 'Acoustic', 'region': 'US'},
    {'technology': None}, {'technology': True}, {'technology': 1}, {'technology': ['Acoustic']},
    {'technology': 'A' * 101}, {'technology': '\ufb03' * 34},
    {'technology': 'Acoustic\x00'}, {'technology': 'Acoustic\u200b'},
])
def test_condition_schema_rejects_unsupported_or_ambiguous_inputs(setup, conditions):
    client, _, _ = setup
    assert create(client, conditions=conditions).status_code == 422


def test_first_observation_and_field_filters_are_anded_with_technology(setup):
    client, registry, _ = setup
    acoustic = create(client, kinds=['variant_observed'], fields=['utqg_treadwear'],
                      conditions={'technology': ' ＡＣＯＵＳＴＩＣ '}).json()
    missing_field = create(client, kinds=['variant_observed'], fields=['never_declared'],
                          conditions={'technology': 'Acoustic'}).json()
    registry.result = success('technical fixture records', [
        variant('A-TECH', 'Acoustic'), variant('B-FEATURE', None, ['Acoustic']),
        variant('C-NON', 'NON Acoustic'), variant('D-UNKNOWN', None),
        variant('E-MARKETING', None, description='Acoustic and PNCS promotional text'),
        variant('F-PNCS', 'PNCS'),
    ])
    result = live(client).json()
    assert result['data_state'] == 'live', result
    items = client.get('/v1/notifications').json()['items']
    assert len(items) == 2
    assert {item['identity']['manufacturer_product_code'] for item in items} == {'A-TECH', 'B-FEATURE'}
    assert all(item['rule_id'] == acoustic['id'] and item['kind'] == 'variant_observed' for item in items)
    assert all(item['rule_id'] != missing_field['id'] and item['previous_snapshot_id'] is None for item in items)
    assert all(item['rule_conditions'] == {'technology': 'Acoustic'} for item in items)
    assert acoustic['conditions'] == {'technology': 'Acoustic'}
    live(client)
    assert client.get('/v1/notifications').json()['total'] == 2


def test_matching_fields_still_require_matching_technology_after_baseline(setup):
    client, registry, _ = setup
    rows = [variant('ACOUSTIC', 'Acoustic'), variant('NOT-ACOUSTIC', 'NON Acoustic')]
    registry.result = success('technical baseline', rows)
    live(client)
    rule = create(client, fields=['utqg_treadwear'], conditions={'technology': 'Acoustic'}).json()
    changed = deepcopy(rows)
    for row in changed:
        row['facts']['utqg_treadwear'] = 420
    registry.result = success('both parameters changed', changed)
    assert live(client).json()['data_state'] == 'live'
    items = client.get('/v1/notifications').json()['items']
    assert len(items) == 1 and items[0]['rule_id'] == rule['id']
    assert items[0]['identity']['manufacturer_product_code'] == 'ACOUSTIC'
    assert items[0]['changes']['utqg_treadwear']['before'] == 300
    assert items[0]['changes']['utqg_treadwear']['after'] == 420


def test_conditions_survive_old_client_edits_archive_restore_and_old_alert_revision(setup):
    client, registry, _ = setup
    rule = create(client, kinds=['variant_observed'], conditions={'technology': 'Acoustic'}).json()
    registry.result = success('condition observation', [variant('ACOUSTIC', 'Acoustic')])
    live(client)
    # An older client does not know the new field. Omission must not broaden a rule.
    old_settings = {key: rule[key] for key in ('name', 'interval_seconds', 'enabled', 'kinds', 'fields')}
    revised = client.put('/v1/alert-rules/' + rule['id'], json={**old_settings,
        'name': 'legacy client rename', 'expected_revision': 1}).json()
    assert revised['conditions'] == {'technology': 'Acoustic'}
    foam = edit(client, revised, conditions={'technology': 'foam'}).json()
    assert foam['conditions'] == {'technology': 'Foam'}
    path = '/v1/alert-rules/' + rule['id']
    archived = client.post(path + '/state', json={'expected_revision': foam['revision'], 'action': 'archive'}).json()
    restored = client.post(path + '/state', json={'expected_revision': archived['revision'], 'action': 'restore'}).json()
    assert not restored['enabled'] and restored['conditions'] == {'technology': 'Foam'}
    history = client.get(path + '?mode=history').json()['history']
    assert history[-1]['conditions'] == history[-2]['conditions'] == {'technology': 'Acoustic'}
    assert all(row['conditions'] == {'technology': 'Foam'} for row in history[:-2])
    old_notice = client.get('/v1/notifications').json()['items'][0]
    assert old_notice['rule_revision'] == 1 and old_notice['rule_conditions'] == {'technology': 'Acoustic'}
    cleared = edit(client, restored, conditions={}).json()
    assert cleared['conditions'] == {}


def test_exact_sku_cannot_be_created_with_conflicting_technology(setup):
    client, registry, _ = setup
    registry.result = success('acoustic sku', [variant('ACOUSTIC', 'Acoustic')])
    identity = live(client).json()['variants'][0]['id']
    assert create(client, variant_id=identity, conditions={'technology': 'PNCS'}).status_code == 422
    assert create(client, variant_id=identity, conditions={'technology': 'Acoustic'}).status_code == 201


def test_empty_technology_is_explicit_unrestricted_condition(setup):
    client, _, _ = setup
    assert create(client, conditions={'technology': '   '}).json()['conditions'] == {}


def test_additive_migration_preserves_legacy_rows_without_rewriting_them(tmp_path):
    url = 'sqlite:///' + (tmp_path / 'legacy-rules.db').as_posix()
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        rule = create(client).json()
        with app.state.database.engine.begin() as connection:
            # Model a database produced before this release; only this temporary
            # database is modified. Existing verifier migration stays installed.
            connection.exec_driver_sql('ALTER TABLE alert_rule_revisions DROP COLUMN conditions')
            connection.execute(text('DELETE FROM tire_schema_versions WHERE version = :version'),
                               {'version': '002_monitor_rule_conditions'})
            before = connection.execute(text('SELECT * FROM alert_rule_revisions')).mappings().all()
    restarted = create_app(url, FixtureRegistry())
    with TestClient(restarted) as client:
        detail = client.get('/v1/alert-rules/' + rule['id'] + '?mode=history').json()
        assert detail['conditions'] == detail['history'][0]['conditions'] == {}
        with restarted.state.database.engine.connect() as connection:
            after = connection.execute(text('SELECT * FROM alert_rule_revisions')).mappings().all()
            assert [{key: value for key, value in row.items() if key != 'conditions'} for row in after] == [dict(row) for row in before]
            assert all(row['conditions'] is None for row in after)
            assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        restarted.state.database.initialize()
        assert edit(client, detail, name='new revision').json()['conditions'] == {}


def verify_monitor_conditions_persistence(url):
    """Shared SQLite/PostgreSQL test: helper joins the caller's atomic transaction."""
    marker = 'conditionhelper-' + uuid4().hex
    registry = FixtureRegistry()
    app = create_app(url, registry)
    with TestClient(app) as client:
        client.get('/health')
        actor = client.cookies.get('tire_local_session')
        payload = RuleCreate(name=marker, source_id='fixture', query={'model': marker},
                             kinds=['variant_observed'], enabled=True, conditions={'technology': 'Acoustic'})
        with app.state.database.sessions() as db:
            QueryService(db, None).lock_ingestion()
            counts = {model: db.scalar(select(func.count()).select_from(model)) for model in (AlertRule, AlertRuleRevision, MonitorJob, AuditEvent)}
            rolled_back = create_rule(db, registry, payload, actor)
            db.rollback()
        with app.state.database.sessions() as db:
            assert db.get(AlertRule, rolled_back['id']) is None
            assert all(db.scalar(select(func.count()).select_from(model)) == total for model, total in counts.items())
            QueryService(db, None).lock_ingestion()
            saved = create_rule(db, registry, payload, actor)
            db.commit()
        row = variant(marker, 'Acoustic')
        row['model'] = marker
        registry.result = success(marker, [row])
        assert live(client, {'query': {'model': marker}, 'fallback_policy': 'never'}).json()['data_state'] == 'live'
        notices = client.get('/v1/notifications').json()['items']
        matching = [item for item in notices if item['rule_id'] == saved['id']]
        assert len(matching) == 1 and matching[0]['rule_conditions'] == {'technology': 'Acoustic'}
        modified = edit(client, saved, conditions={'technology': 'PNCS'}).json()
        assert modified['conditions'] == {'technology': 'PNCS'}
    restart = create_app(url, registry)
    with TestClient(restart) as client:
        restored = client.get('/v1/alert-rules/' + saved['id'] + '?mode=history').json()
        assert restored['conditions'] == {'technology': 'PNCS'}
        assert restored['history'][-1]['conditions'] == {'technology': 'Acoustic'}
        matching = [item for item in client.get('/v1/notifications').json()['items'] if item['rule_id'] == saved['id']]
        assert matching[0]['rule_conditions'] == {'technology': 'Acoustic'}
    return {'conditions': 'exact_identity_only', 'caller_transaction_rollback': True,
            'rule_revision_and_notification_restart': True}


def test_creation_helper_rollback_and_persistence(tmp_path):
    verify_monitor_conditions_persistence('sqlite:///' + (tmp_path / 'conditions-helper.db').as_posix())
