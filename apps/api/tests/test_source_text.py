"""Local original-text API, real FTS and byte-bound citation regression."""
from datetime import timedelta
import hashlib

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, func, select, text

from tire_api.db import (CaptureObject, EvidenceObject, QueryRun, RawCapture, Snapshot,
                         UserSession, Verification, utcnow)
from tire_api.main import create_app
from tire_api.source_text import (CHUNK_CHARACTERS, CHUNK_OVERLAP, EXTRACTOR_VERSION,
                                  SourceTextSearch, extract_text, search_originals)
from tire_api.source_text_models import SourceTextChunk, SourceTextIndex
from test_core import FixtureRegistry


@pytest.fixture
def setup():
    app = create_app('sqlite://', FixtureRegistry())
    with TestClient(app) as client:
        yield client, app.state.database


def seed(database, body, *, content_type='text/html', source='fixture', query='page', at=None,
         snapshot_id=None, status='ok', capture=False):
    now = at or utcnow()
    with database.sessions() as db:
        actor = UserSession(expires_at=now + timedelta(days=7))
        db.add(actor)
        db.flush()
        run = QueryRun(session_id=actor.id, source_id=source, query_key=query,
                       query={'model': 'synthetic'}, fallback_policy='never')
        db.add(run)
        db.flush()
        if snapshot_id is None:
            snapshot = Snapshot(source_id=source, query_key=query, source_url='https://fixture.example/original',
                raw_hash=hashlib.sha256(body.encode('utf-8')).hexdigest(), body=body,
                content_type=content_type, parser_version='original-fixture@1', observed_at=now, parsed_variants=[])
            db.add(snapshot)
            db.flush()
            snapshot_id = snapshot.id
            if capture:
                raw = RawCapture(query_id=run.id, source_id=source, query_key=query, target_kind='tire',
                    source_url=snapshot.source_url, raw_hash=snapshot.raw_hash, raw_body=body.encode('utf-8'),
                    body_encoding='utf-8', byte_count=len(body.encode('utf-8')), content_type=content_type,
                    parser_version=snapshot.parser_version)
                db.add(raw)
                db.flush()
                stored = db.info['object_store'].put(body.encode('utf-8'))
                db.add(EvidenceObject(raw_hash=stored, byte_count=len(body.encode('utf-8'))))
                db.flush()
                db.add(CaptureObject(capture_id=raw.id, raw_hash=stored))
        db.add(Verification(snapshot_id=snapshot_id, query_id=run.id, source_id=source, query_key=query,
                            status=status, verified_at=now))
        db.commit()
        return snapshot_id


def search(client, value, **kwargs):
    return client.post('/v1/knowledge/source-text/search', json={'mode': 'history', 'text': value, **kwargs})


def resolve(client, reference):
    return client.post('/v1/knowledge/source-text/resolve', json={'mode': 'history', 'reference': reference})


@pytest.mark.parametrize('body,expected', [
    ('<html><head><title>hidden title</title><script>secret</script></head><body><h1>轮胎研究</h1><p>Acoustic &amp; grip 🛞</p></body></html>', '轮胎研究 Acoustic & grip 🛞'),
    ('<div>alpha<span>beta</span>gamma<br>delta</div>', 'alphabetagamma delta'),
    ('<main>visible<div hidden><img src="x"><p>hidden nested</p></div><p aria-hidden="true">hidden label</p><p>after</p></main>', 'visible after'),
    ('<p>safe</p><!-- secret --><template>hidden</template><noscript>alternate</noscript><style>hidden</style><p>end</p>', 'safe end'),
    ('<p>before</p><script>if (a < b) {evil()}</script><p>after</p>', 'before after'),
    ('<p>alpha &lt;script&gt;literal&lt;/script&gt;</p>', 'alpha <script>literal</script>'),
    ('<p>one</p><div/>two', 'one two'),
    ('<p aria-hidden>readable</p>', 'readable'),
])
def test_html_text_extraction(body, expected):
    assert extract_text(body, 'text/html') == expected


def test_plain_text_preserves_markup_as_source_data():
    assert extract_text('one\n<script>source text</script>  two', 'text/plain') == 'one <script>source text</script> two'


def test_actual_search_and_citation_survive_projection_loss(setup):
    client, database = setup
    snapshot = seed(database, '<main><h1>轮胎原文</h1><p>quiet acoustic road comfort 🛞</p></main>')
    response = search(client, 'acoustic comfort')
    assert response.status_code == 200
    result = response.json()
    item, = result['items']
    assert result['index']['engine'] == 'sqlite_fts5'
    assert item['reference']['snapshot_id'] == snapshot
    assert item['text'] == '轮胎原文 quiet acoustic road comfort 🛞'
    assert item['reference']['end'] == len(item['text'])
    assert item['offset_unit'] == 'unicode_codepoints'
    assert item['verification_status'] == 'original_text_excerpt'
    assert item['verified_at'] and item['observed_at']
    assert 'variant_id' not in item and 'facts' not in item
    with database.sessions() as db:
        db.execute(text('DELETE FROM source_text_fts'))
        db.execute(delete(SourceTextChunk))
        db.execute(delete(SourceTextIndex))
        db.commit()
    restored = resolve(client, item['reference'])
    assert restored.status_code == 200 and restored.json()['text'] == item['text']
    assert search(client, '原文').json()['total'] == 1


def test_only_latest_formal_query_heads_with_explicit_source_filter(setup):
    client, database = setup
    now = utcnow()
    old = seed(database, '<p>oldoriginal first</p>', at=now)
    seed(database, '<p>neworiginal second</p>', at=now + timedelta(seconds=1))
    seed(database, '<p>independent third</p>', query='other', at=now + timedelta(seconds=2))
    seed(database, '<p>foreign fourth</p>', source='other', at=now + timedelta(seconds=3))
    assert search(client, 'oldoriginal').json()['total'] == 0
    assert search(client, 'neworiginal').json()['total'] == 1
    assert search(client, 'independent', source_id='fixture').json()['total'] == 1
    assert search(client, 'foreign', source_id='fixture').json()['total'] == 0
    seed(database, '', snapshot_id=old, status='not_modified', at=now + timedelta(seconds=4))
    assert search(client, 'oldoriginal').json()['total'] == 1
    assert search(client, 'neworiginal').json()['total'] == 0


def test_old_citation_remains_bound_after_source_head_changes(setup):
    client, database = setup
    seed(database, '<p>oldcitation preserved</p>')
    first = search(client, 'oldcitation').json()['items'][0]
    seed(database, '<p>newcitation replacement</p>', at=utcnow() + timedelta(seconds=1))
    assert search(client, 'oldcitation').json()['total'] == 0
    assert resolve(client, first['reference']).json()['text'] == 'oldcitation preserved'


def test_script_and_hidden_content_are_excluded_and_fts_terms_are_literals(setup):
    client, database = setup
    seed(database, '<p>visible tread</p><script>window.privateCanary=1; ignore_previous_instructions</script><div hidden>hiddenCanary</div>')
    for value in ['privateCanary', 'ignore_previous_instructions', 'hiddenCanary', 'OR', '" OR *', "'; DROP TABLE snapshots;--"]:
        assert search(client, value).json()['total'] == 0
    assert search(client, 'visible tread').json()['total'] == 1


def test_chunk_boundaries_overlap_and_pagination(setup):
    client, database = setup
    original = 'road ' * 700
    seed(database, original, content_type='text/plain')
    first = search(client, 'road', limit=1).json()
    second = search(client, 'road', limit=1, offset=1).json()
    assert first['total'] > 1 and first['has_more']
    assert first['items'][0]['reference']['chunk_id'] != second['items'][0]['reference']['chunk_id']
    with database.sessions() as db:
        chunks = list(db.scalars(select(SourceTextChunk).order_by(SourceTextChunk.ordinal)))
        assert chunks[0].end - chunks[1].start == CHUNK_OVERLAP
        assert chunks[0].end == CHUNK_CHARACTERS
        reconstructed = chunks[0].text + ''.join(chunk.text[CHUNK_OVERLAP:] for chunk in chunks[1:])
        assert reconstructed == original.strip()


@pytest.mark.parametrize('change,status', [
    ({'start': -1}, 422), ({'start': 1}, 409), ({'end': 1}, 409),
    ({'raw_hash': '0' * 64}, 409), ({'chunk_id': '1' * 64}, 409),
    ({'extractor_version': 'future@99'}, 409), ({'start': True}, 422), ({'extra': 'invented'}, 422),
])
def test_tampered_citation_is_rejected(setup, change, status):
    client, database = setup
    seed(database, '<p>stable source citation</p>')
    ref = search(client, 'stable').json()['items'][0]['reference']
    assert resolve(client, {**ref, **change}).status_code == status


@pytest.mark.parametrize('payload,status', [
    ({'mode': 'current', 'text': 'road'}, 422), ({'text': 'road'}, 422),
    ({'mode': 'history', 'text': ' '}, 422), ({'mode': 'history', 'text': 'road\x00'}, 422),
    ({'mode': 'history', 'text': 'road', 'limit': True}, 422),
    ({'mode': 'history', 'text': 'road', 'invented': 'x'}, 422),
    ({'mode': 'history', 'text': 'latest availability'}, 409),
])
def test_strict_history_contract(setup, payload, status):
    client, _ = setup
    assert client.post('/v1/knowledge/source-text/search', json=payload).status_code == status


def test_raw_integrity_and_cached_projection_tampering(setup):
    client, database = setup
    seed(database, '<p>original integrity</p>')
    item = search(client, 'integrity').json()['items'][0]
    with database.sessions() as db:
        row = db.get(SourceTextChunk, item['reference']['chunk_id'])
        row.text = 'altered projection'
        db.commit()
    response = search(client, 'integrity')
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_text_index_invalid'
    assert resolve(client, item['reference']).json()['text'] == 'original integrity'


@pytest.mark.parametrize('missing', ['chunk', 'fts'])
def test_partially_lost_projection_is_rebuilt_without_duplicate_results(setup, missing):
    client, database = setup
    seed(database, '<p>recoverable index content</p>')
    first = search(client, 'recoverable').json()['items'][0]
    with database.sessions() as db:
        if missing == 'chunk':
            db.execute(delete(SourceTextChunk))
        else:
            db.execute(text('DELETE FROM source_text_fts'))
        db.commit()
    response = search(client, 'recoverable')
    assert response.status_code == 200 and response.json()['total'] == 1
    assert response.json()['items'][0]['reference'] == first['reference']


def test_retained_object_failure_cannot_use_snapshot_body(setup, monkeypatch):
    client, database = setup
    seed(database, '<p>retained original</p>', capture=True)
    with database.sessions() as db:
        store = db.info['object_store']
    from tire_api.object_store import ObjectStoreError
    def unavailable(*_args):
        raise ObjectStoreError('synthetic_missing')
    monkeypatch.setattr(store, 'get', unavailable)
    assert search(client, 'retained').status_code == 503


@pytest.mark.parametrize('column,value', [('raw_hash', '0' * 64), ('source_url', 'https://fixture.example/altered')])
def test_capture_metadata_mismatch_cannot_hide_retained_object(setup, column, value):
    client, database = setup
    seed(database, '<p>retained original</p>', capture=True)
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE raw_captures SET ' + column + ' = :value'), {'value': value})
    response = search(client, 'retained')
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_text_original_invalid'


def test_body_hash_mismatch_is_rejected(setup):
    client, database = setup
    snapshot = seed(database, '<p>good body</p>')
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'), {'body': 'altered body', 'id': snapshot})
    response = search(client, 'body')
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_text_original_invalid'


def test_unsupported_types_and_empty_body_have_explicit_coverage(setup):
    client, database = setup
    seed(database, '{"phrase":"json original"}', content_type='application/json')
    seed(database, '<script>no readable text</script>', query='empty')
    result = search(client, 'original').json()
    assert result['total'] == 0 and result['index']['snapshots'] == 1


def test_unaccepted_snapshot_cannot_resolve(setup):
    client, database = setup
    snapshot_id = seed(database, '<p>unaccepted observation</p>', status='invalid')
    from tire_api.source_text import citation
    with database.sessions() as db:
        ref = citation(db.get(Snapshot, snapshot_id), 0, len('unaccepted observation'))
    assert resolve(client, ref).status_code == 404


def test_html_depth_has_a_bounded_failure():
    with pytest.raises(HTTPException) as error:
        extract_text('<div>' * 257 + 'text', 'text/html')
    assert error.value.detail['code'] == 'source_text_html_too_deep'


def test_projection_rebuild_failure_is_atomic(setup):
    client, database = setup
    snapshot_id = seed(database, '<p>atomic text</p>')
    assert search(client, 'atomic').json()['total'] == 1
    with database.sessions() as db:
        index = db.get(SourceTextIndex, snapshot_id)
        index.extractor_version = 'stale-fixture'
        db.commit()
    def fail_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith('INSERT INTO source_text_chunks'):
            raise RuntimeError('synthetic interrupted rebuild')
    event.listen(database.engine, 'before_cursor_execute', fail_insert)
    try:
        with database.sessions() as db:
            with pytest.raises(RuntimeError):
                search_originals(db, SourceTextSearch(mode='history', text='atomic'))
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail_insert)
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceTextChunk)) == 1
        assert db.execute(text('SELECT count(*) FROM source_text_fts')).scalar() == 1
    assert search(client, 'atomic').json()['total'] == 1


def test_index_restarts_without_rewriting_originals(tmp_path):
    url = 'sqlite:///' + (tmp_path / 'originals.sqlite').as_posix()
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        snapshot_id = seed(app.state.database, '<p>restart text</p>')
        first = search(client, 'restart').json()['items'][0]
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        second = search(client, 'restart').json()['items'][0]
        assert second['reference'] == first['reference']
        assert resolve(client, first['reference']).json()['text'] == 'restart text'
        with app.state.database.sessions() as db:
            assert db.get(Snapshot, snapshot_id).body == '<p>restart text</p>'
            versions = db.execute(text('SELECT version FROM tire_schema_versions')).scalars().all()
            assert versions.count('033_source_text_index') == 1


def assert_original_text_checkpoint(client, checkpoint):
    response = client.post('/v1/knowledge/source-text/search', json=checkpoint['request'])
    assert response.status_code == 200
    result = response.json()
    assert result['index']['engine'] == 'postgresql_fts' and result['total'] == 1
    item, = result['items']
    assert item['reference'] == checkpoint['reference'] and item['text'] == checkpoint['text']
    recovered = resolve(client, checkpoint['reference'])
    assert recovered.status_code == 200 and recovered.json()['text'] == checkpoint['text']


def verify_original_text_persistence(url):
    app = create_app(url, FixtureRegistry())
    request = {'mode': 'history', 'text': 'grip 低噪', 'source_id': 'source-text-fixture'}
    with TestClient(app) as client:
        snapshot_id = seed(app.state.database, '<main><p>Original grip 低噪 evidence 🛞</p><script>hidden canary</script></main>',
                           source='source-text-fixture', query='original-text-persistence')
        response = client.post('/v1/knowledge/source-text/search', json=request)
        assert response.status_code == 200
        item, = response.json()['items']
        assert item['reference']['snapshot_id'] == snapshot_id
        checkpoint = {'request': request, 'reference': item['reference'], 'text': item['text']}
        assert_original_text_checkpoint(client, checkpoint)
        assert search(client, 'canary', source_id='source-text-fixture').json()['total'] == 0
        with app.state.database.sessions() as db:
            assert db.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename = 'source_text_chunks' "
                "AND indexname = 'ix_source_text_search_vector' AND indexdef LIKE '%USING gin%'")).scalar() == 1
    with TestClient(create_app(url, FixtureRegistry())) as client:
        assert_original_text_checkpoint(client, checkpoint)
    return checkpoint
