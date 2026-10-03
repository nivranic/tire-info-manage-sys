"""Ask/never express preference; they do not authorize unavailable-source reads."""
import pytest

from tire_api.query_fallback_policies import QueryFallbackUse
from test_core import live
from test_query_fallback_policies49 import allow, apply, count, preview, scope, setup, trace, business_reads


@pytest.mark.parametrize('mode', ['ask', 'never'])
def test_registered_false_source_can_save_preference_but_not_grant_read(setup, monkeypatch, mode):
    client, registry, database = setup
    live(client)
    monkeypatch.setenv('TI_DISABLED_SOURCES', 'fixture')
    source = client.get('/v1/source-settings/fixture').json()
    assert source['can_fetch'] is False and source['management']['access_generation'] == 0
    saved = allow(client, mode)
    assert saved['mode'] == mode and saved['state'] == 'enabled'
    assert preview(client, 'query_allow').status_code == 409
    statements = trace(database)
    registry.result = {'status': 'unavailable', 'reason': 'source_disabled'}
    result = live(client).json()
    assert result['variants'] == [] and not business_reads(statements)
    assert result['data_state'] == ('source_unavailable' if mode == 'never' else 'consent_required')
    assert count(database, QueryFallbackUse) == 0


@pytest.mark.parametrize('mode', ['ask', 'never'])
def test_false_source_preference_still_rejects_unknown_kind_generation_and_stale_preview(setup, monkeypatch, mode):
    client, _, _ = setup
    prepared = preview(client, mode).json()
    monkeypatch.setenv('TI_DISABLED_SOURCES', 'fixture')
    assert apply(client, prepared).json()['detail']['code'] == 'query_fallback_preview_stale'
    assert preview(client, mode, scope(source='unknown-directory')).status_code == 404
    assert preview(client, mode, scope(generation=1)).status_code == 409
    assert preview(client, mode, scope(kind='vehicle_fitments')).status_code == 422


@pytest.mark.parametrize('equal_time', [False, True])
def test_same_scope_allows_choose_latest_approval_then_ascending_policy_id(setup, monkeypatch, equal_time):
    from datetime import timedelta
    import tire_api.query_fallback_policies as module
    client, registry, _ = setup
    live(client)
    # Keep the controlled policy clock beyond the ORM's real created_at default.
    now = module.utcnow() + timedelta(seconds=60)
    monkeypatch.setattr(module, 'utcnow', lambda: now)
    first = allow(client)
    if not equal_time:
        monkeypatch.setattr(module, 'utcnow', lambda: now + timedelta(seconds=2))
    second = allow(client)
    registry.result = {'status': 'unavailable', 'reason': 'upstream_timeout'}
    result = live(client).json()
    expected = min(first['id'], second['id']) if equal_time else second['id']
    assert result['fallback_authorization']['use']['policy_id'] == expected
