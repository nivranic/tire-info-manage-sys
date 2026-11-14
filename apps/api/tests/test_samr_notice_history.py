"""Chinese notice versions through normal adoption, old snapshots and history APIs."""
from copy import deepcopy

import pytest
from sqlalchemy import select, text

from test_samr import IDENTITY, NOTICE, SEARCH, notice_body
from test_samr_recalls import context, count, run
from tire_api.adapters import samr as source
from tire_api.samr_notice_history import SamrNoticeChange, SamrNoticeObservation, SamrNoticeRevision

ARTICLE_ID = 'a' * 32
MODELS = (SamrNoticeRevision, SamrNoticeObservation, SamrNoticeChange)


def revised(adapter, *, content='A', pub_date='2026-06-22 11:48', prefix=''):
    async def fetch(query, cached=None, *, on_observation=None):
        adapter.calls.append(deepcopy(query))
        body = prefix + notice_body(query['reference']).replace('合成处理措施。', content)
        body = body.replace('2026-06-22 11:48', pub_date)
        value = {'status': 'ok', 'url': source.query_url(query), 'body': body,
            'content_type': 'text/html', 'parser_version': source.PARSER_VERSION,
            'parser_identity': deepcopy(IDENTITY), 'document': source.parse_document(body, query)}
        if on_observation:
            on_observation(value)
        return value
    adapter.fetch = fetch


def history(client, identity=ARTICLE_ID, **params):
    response = client.get(f'/v1/samr-recalls/notices/{identity}/history', params={'mode': 'history', **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_repeated_304_and_serializer_changes_preserve_content_versions(context):
    client, adapter, database = context
    first = run(client)
    run(client)
    adapter.not_modified = True
    assert run(client)['data_state'] == 'live_verified_304'
    assert history(client)['total'] == 1
    revised(adapter, content='合成处理措施。', prefix='\n')
    run(client)
    value = history(client)
    assert value['total'] == 2 and value['head']['sequence'] == 2
    assert [count(database, model) for model in MODELS] == [1, 2, 1]
    assert value['head']['event'] is None
    assert client.get(first['provenance'][0]['evidence_path']).json()['body'] == notice_body()


def test_field_changes_and_content_reversion_bind_both_originals(context):
    client, adapter, database = context
    for content in ['A', 'B', 'A']:
        revised(adapter, content=content)
        assert run(client)['data_state'] == 'live'
    value = history(client)
    assert [count(database, model) for model in MODELS] == [2, 3, 3]
    latest, middle, first = value['observations']
    assert latest['revision']['id'] == first['revision']['id']
    assert latest['revision']['revision'] == 1 and middle['revision']['revision'] == 2
    assert latest['event']['before_revision_id'] == middle['revision']['id']
    assert latest['event']['after_revision_id'] == first['revision']['id']
    assert latest['event']['previous_snapshot_id'] == middle['snapshot_id']
    assert latest['event']['changes']['text']['before'].endswith('B\n合成外部附件')
    assert latest['event']['changes']['text']['after'].endswith('A\n合成外部附件')
    for row in value['observations']:
        saved = client.get(row['evidence_path']).json()
        assert saved['id'] == row['snapshot_id'] and saved['query'] == NOTICE
        assert row['revision']['notice'] == source.parse_document(saved['body'], saved['query'])['notice']


def test_metadata_dates_are_retained_in_system_observation_order(context):
    client, adapter, _database = context
    revised(adapter, pub_date='2026-06-22 11:48')
    run(client)
    revised(adapter, pub_date='2025-06-22 11:48')
    run(client)
    value = history(client)
    assert value['head']['revision']['notice']['pub_date_raw'].startswith('2025-')
    assert value['head']['revision']['notice']['published_date'] == '2021-07-23'
    assert value['head']['event']['changes']['pub_date_raw'] == {'before': '2026-06-22 11:48', 'after': '2025-06-22 11:48'}
    assert value['applicability'] == 'not_assessed' and value['data_state'] == 'local_snapshot'


def test_native_article_ids_with_same_title_remain_distinct(context):
    client, adapter, database = context
    first = run(client)
    other_query = {**NOTICE, 'reference': NOTICE['reference'].replace(ARTICLE_ID, 'b' * 32)}
    second = run(client, other_query)
    a, b = history(client), history(client, 'b' * 32)
    assert a['head']['revision']['notice']['title'] == b['head']['revision']['notice']['title']
    assert a['head']['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert b['head']['snapshot_id'] == second['provenance'][0]['snapshot_id']
    assert [count(database, model) for model in MODELS] == [2, 2, 2]


def test_search_absence_offline_and_history_fallback_do_not_create_observations(context):
    client, adapter, database = context
    run(client)
    run(client, SEARCH)
    adapter.offline = True
    failed = run(client)
    assert failed['data_state'] == 'consent_required'
    consent = client.post('/v1/fallback-consents', json={'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'}).json()
    assert run(client, consent_id=consent['id'])['data_state'] == 'local_snapshot'
    assert [count(database, model) for model in MODELS] == [1, 1, 1]


def test_legacy_projection_is_atomic_repeatable_and_source_free(context, monkeypatch):
    import tire_api.samr_notice_history as module
    client, adapter, database = context
    with monkeypatch.context() as patch:
        patch.setattr(module, 'backfill_notice_history', lambda _db: 0)
        for content in ['A', 'B', 'A']:
            revised(adapter, content=content)
            run(client)
    assert count(database, SamrNoticeObservation) == 0
    calls = len(adapter.calls)
    first = history(client)
    assert history(client) == first and first['total'] == 3
    assert len(adapter.calls) == calls
    assert [count(database, model) for model in MODELS] == [2, 3, 3]


def test_fixed_history_range_stays_stable_after_new_observation(context):
    client, adapter, _database = context
    for content in ['A', 'B', 'C']:
        revised(adapter, content=content)
        run(client)
    first = history(client, limit=1)
    revised(adapter, content='D')
    run(client)
    second = history(client, limit=1, offset=1, through_sequence=first['through_sequence'])
    assert second['total'] == 3 and second['head'] == first['head']
    assert second['observations'][0]['sequence'] == 2
    assert history(client)['total'] == 4


@pytest.mark.parametrize('model', MODELS)
def test_notice_history_rows_are_append_only(context, model):
    client, _adapter, database = context
    run(client)
    with database.sessions() as db:
        row = db.scalar(select(model))
        row.article_id = 'b' * 32
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
        db.rollback()
        db.delete(db.scalar(select(model)))
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
        db.rollback()


@pytest.mark.parametrize('table,column,value', [
    ('samr_notice_revisions', 'content_hash', 'corrupt'),
    ('samr_notice_observations', 'article_id', 'b' * 32),
    ('samr_notice_changes', 'article_id', 'b' * 32),
    ('samr_recall_snapshots', 'body', 'corrupt'),
])
def test_corrupt_history_bindings_fail_closed(context, table, column, value):
    client, _adapter, database = context
    run(client)
    with database.engine.begin() as connection:
        connection.execute(text(f'UPDATE {table} SET {column}=:value'), {'value': value})
    # An observation moved to a different identity makes the original article absent.
    response = client.get(f'/v1/samr-recalls/notices/{ARTICLE_ID}/history', params={'mode': 'history'})
    assert response.status_code == (404 if table == 'samr_notice_observations' else 503)


def test_corrupt_legacy_projection_rolls_back_all_new_rows(context, monkeypatch):
    import tire_api.samr_notice_history as module
    client, adapter, database = context
    with monkeypatch.context() as patch:
        patch.setattr(module, 'backfill_notice_history', lambda _db: 0)
        run(client)
        revised(adapter)
        second = run(client)
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE samr_recall_snapshots SET body=:body WHERE id=:id'),
            {'body': 'corrupt', 'id': second['provenance'][0]['snapshot_id']})
    assert client.get(f'/v1/samr-recalls/notices/{ARTICLE_ID}/history', params={'mode': 'history'}).status_code == 503
    assert [count(database, model) for model in MODELS] == [0, 0, 0]


@pytest.mark.parametrize('identity', ['a' * 31, 'a' * 33, 'A' * 32, 'g' * 32, '１' * 32])
def test_invalid_native_id_is_rejected(context, identity):
    client, _adapter, _database = context
    assert client.get(f'/v1/samr-recalls/notices/{identity}/history', params={'mode': 'history'}).status_code == 422


def test_explicit_history_and_bounded_range_are_required(context):
    client, _adapter, _database = context
    path = f'/v1/samr-recalls/notices/{ARTICLE_ID}/history'
    assert client.get(path).status_code == 422
    assert client.get(path, params={'mode': 'history'}).status_code == 404
    run(client)
    for params in [{'limit': 51}, {'offset': -1}, {'offset': 2 ** 63}, {'through_sequence': 0}, {'through_sequence': 2}]:
        assert client.get(path, params={'mode': 'history', **params}).status_code == 422
