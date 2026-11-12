"""Original text through production HTTP and ledgers, with synthetic vector storage."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from tire_api import embedding_api, embedding_service
from tire_api.db import utcnow
from tire_api.dense import capability
from tire_api.embedding_models import EmbeddingCache, EmbeddingCompletion, EmbeddingPlan, EmbeddingRequest
from tire_api.main import create_app
from tire_api.text_embedding_models import TextEmbeddingAuthorization
from tire_api.text_embeddings import TEXT_CONTRACT
from admin_support import register_admin
from test_core import FixtureRegistry
from test_document_text import indexed_document, search as pdf_search
from test_embeddings import SyntheticEmbeddings, settings
from test_source_text import search, seed


@pytest.fixture
def setup(monkeypatch):
    settings(monkeypatch)
    # This fixture exercises HTTP, SQLite and durable application contracts.
    # Real pgvector storage and HNSW are covered by a separate PostgreSQL run.
    monkeypatch.setattr(embedding_service, 'capability', lambda db: (True, None))
    monkeypatch.setattr(embedding_service, 'mirror_cache', lambda db, cached: None)
    monkeypatch.setattr(embedding_api, 'ensure_hnsw', lambda db, config: None)
    app = create_app('sqlite://', FixtureRegistry())
    provider = SyntheticEmbeddings()
    app.state.embedding_adapter = provider
    with TestClient(app) as client:
        yield client, app.state.database, provider


def selection(client, database, body='<p>原件正文 acoustic comfort 🛞</p>', **options):
    identity = seed(database, body, **options)
    item = next(item for item in search(client, 'acoustic').json()['items']
                if item['reference']['snapshot_id'] == identity)
    return {'kind': 'source_text', 'reference': item['reference']}


def authorize(client, selected, **options):
    request = {'selection': selected, 'expected_revision': 0, 'action': 'grant',
        'rights_basis': '自有合成材料，允许本次指定接收端的正文向量用途',
        'privacy_class': 'public', 'expires_at': None, 'acknowledged': True, **options}
    return client.post('/v1/knowledge/text-embedding-authorizations', json=request)


def plan(client, selected):
    return client.post('/v1/knowledge/text-embedding-plans', json={'selections': [selected]})


def build(client, identity, key=None, consent=True):
    return client.post('/v1/knowledge/embedding-runs', headers={'Idempotency-Key': key or str(uuid4())},
        json={'plan_id': identity, 'allow_external_processing': consent})


def granted(setup):
    client, database, provider = setup
    register_admin(client)
    selected = selection(client, database)
    response = authorize(client, selected)
    assert response.status_code == 200, response.text
    return selected


def test_preview_and_permissions_do_not_dispatch_or_reserve(setup):
    client, database, provider = setup
    selected = selection(client, database)
    response = client.post('/v1/knowledge/text-embedding-authorizations/preview', json={'selection': selected})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['text'] == '原件正文 acoustic comfort 🛞'
    assert value['authorization'] == {'state': 'missing', 'revision': 0, 'revision_id': None}
    assert value['recipient']['provider'] == 'openai_embeddings'
    assert 'synthetic-never-live' not in response.text
    assert client.post('/v1/knowledge/text-embedding-authorizations', json={}).status_code == 403
    assert plan(client, selected).status_code == 403
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 0
    assert not provider.calls


def test_authorization_optimistic_revision_and_revocation(setup):
    client, _database, provider = setup
    selected = granted(setup)
    assert authorize(client, selected).status_code == 409
    response = authorize(client, selected, action='revoke', expected_revision=1)
    assert response.status_code == 200 and response.json()['authorization']['state'] == 'revoked'
    assert plan(client, selected).status_code == 403
    assert authorize(client, selected, expected_revision=2).status_code == 200
    assert plan(client, selected).status_code == 200
    assert not provider.calls


def test_build_uses_original_text_distinct_cache_and_shared_ledger(setup):
    client, database, provider = setup
    selected = granted(setup)
    prepared = plan(client, selected)
    assert prepared.status_code == 200, prepared.text
    value = prepared.json()
    assert value['text_contract'] == TEXT_CONTRACT and value['pending_chunks'] == 1
    assert value['selections'][0]['selection'] == selected
    key = str(uuid4())
    response = build(client, value['id'], key)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'completed' and result['result']['written_chunks'] == 1, result
    assert result['result']['text_contract'] == TEXT_CONTRACT
    assert provider.calls[0][2] == ['原件正文 acoustic comfort 🛞']
    assert build(client, value['id'], key).json() == result
    assert len(provider.calls) == 1
    with database.sessions() as db:
        cache, = db.scalars(select(EmbeddingCache)).all()
        request, = db.scalars(select(EmbeddingRequest)).all()
        assert cache.text_contract == TEXT_CONTRACT and cache.privacy_class == 'public'
        assert db.get(EmbeddingCompletion, request.id).usage['total_tokens'] == 10
        assert request.kind == 'index' and request.plan_id == value['id']
    cached = plan(client, selected).json()
    assert cached['pending_chunks'] == 0 and cached['reserved_tokens'] == 0
    assert build(client, cached['id']).json()['state'] == 'completed'
    assert len(provider.calls) == 1
    history = client.get('/v1/knowledge/embedding-runs?mode=history').json()['items']
    assert len(history) == 2


@pytest.mark.parametrize('case', ['consent', 'revoked', 'renewed', 'original', 'plan', 'model', 'private'])
def test_changed_authority_or_inputs_refuse_before_provider(setup, monkeypatch, case):
    client, database, provider = setup
    selected = granted(setup)
    prepared = plan(client, selected).json()
    if case == 'revoked':
        assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
    elif case == 'renewed':
        assert authorize(client, selected, expected_revision=1).status_code == 200
    elif case == 'private':
        assert authorize(client, selected, expected_revision=1, privacy_class='private').status_code == 200
    elif case == 'original':
        with database.sessions() as db:
            db.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'),
                       {'body': '<p>changed</p>', 'id': selected['reference']['snapshot_id']})
            db.commit()
    elif case == 'plan':
        with database.sessions() as db:
            row = db.get(EmbeddingPlan, prepared['id'])
            value = deepcopy(row.payload)
            value['documents'][0]['chunks'][0]['text'] = 'tampered body'
            import json
            db.execute(text('UPDATE embedding_plans SET payload = :payload WHERE id = :id'),
                       {'payload': json.dumps(value), 'id': row.id})
            db.commit()
    elif case == 'model':
        monkeypatch.setenv('TI_OPENAI_EMBEDDING_MODEL', 'different-synthetic-model')
    response = build(client, prepared['id'], consent=case != 'consent')
    assert response.status_code in (403, 409, 422), response.text
    assert not provider.calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 0


def test_final_dispatch_rechecks_revoked_permission_and_records_zero_usage(setup, monkeypatch):
    client, database, provider = setup
    selected = granted(setup)
    prepared = plan(client, selected).json()
    check = embedding_api.check_embedding_dispatch
    def revoke_before_dispatch(*args, **kwargs):
        assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
        return check(*args, **kwargs)
    monkeypatch.setattr(embedding_api, 'check_embedding_dispatch', revoke_before_dispatch)
    response = build(client, prepared['id'])
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'failed' and value['error_code'] == 'text_embedding_use_not_allowed'
    assert value['usage']['total_tokens'] == 0 and not provider.calls
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EmbeddingCache)) == 0


def test_revocation_during_provider_retains_actual_usage_and_no_vector(setup):
    client, database, provider = setup
    selected = granted(setup)
    prepared = plan(client, selected).json()
    embed = provider.embed
    async def revoke_during_call(config, inputs):
        receipt = await embed(config, inputs)
        assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
        return receipt
    provider.embed = revoke_during_call
    response = build(client, prepared['id'])
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'failed' and value['error_code'] == 'text_embedding_use_not_allowed'
    assert value['usage']['total_tokens'] == 10 and len(provider.calls) == 1
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EmbeddingCache)) == 0


def test_private_permission_requires_private_processing_and_distinct_cache(setup, monkeypatch):
    client, _database, provider = setup
    selected = granted(setup)
    first = plan(client, selected).json()
    assert build(client, first['id']).json()['state'] == 'completed'
    assert authorize(client, selected, expected_revision=1, privacy_class='private').status_code == 200
    assert plan(client, selected).status_code == 403
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    second = plan(client, selected).json()
    assert second['pending_chunks'] == 1
    assert build(client, second['id']).json()['state'] == 'completed'
    assert len(provider.calls) == 2


def test_pdf_vectors_recover_original_page_and_use_same_run_contract(setup):
    client, _database, provider = setup
    register_admin(client)
    document, _state = indexed_document(client, pages=('原始PDF acoustic 🛞', '第二页正文'))
    item, = pdf_search(client, 'acoustic', document_id=document['id']).json()['items']
    selected = {'kind': 'document_text', 'reference': item['reference']}
    assert authorize(client, selected).status_code == 200
    prepared = plan(client, selected)
    assert prepared.status_code == 200, prepared.text
    response = build(client, prepared.json()['id'])
    assert response.status_code == 200 and response.json()['state'] == 'completed', response.text
    assert provider.calls[0][2] == ['原始PDF acoustic 🛞']


@pytest.mark.parametrize('operation', ['update', 'delete', 'replace', 'orm'])
def test_authorizations_are_append_only_at_orm_and_sql_boundaries(setup, operation):
    client, database, _provider = setup
    granted(setup)
    with database.sessions() as db:
        row = db.scalar(select(TextEmbeddingAuthorization))
        with pytest.raises((ValueError, DBAPIError), match='text_embedding_authorization_immutable'):
            if operation == 'orm':
                row.revision = 99
                db.flush()
            elif operation == 'replace':
                db.execute(text('INSERT OR REPLACE INTO text_embedding_authorizations SELECT * '
                                'FROM text_embedding_authorizations WHERE id = :id'), {'id': row.id})
            else:
                statement = 'UPDATE text_embedding_authorizations SET revision = 99' if operation == 'update' else 'DELETE FROM text_embedding_authorizations'
                db.execute(text(statement))
        db.rollback()
        assert db.scalar(select(func.count()).select_from(TextEmbeddingAuthorization)) == 1


def test_actual_sqlite_capability_still_refuses_before_paid_call(setup, monkeypatch):
    client, _database, provider = setup
    selected = granted(setup)
    monkeypatch.setattr(embedding_service, 'capability', capability)
    response = plan(client, selected)
    assert response.status_code == 503 and not provider.calls


def test_permission_can_be_revoked_after_original_becomes_unreadable(setup):
    client, database, provider = setup
    selected = granted(setup)
    with database.sessions() as db:
        db.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'),
            {'body': 'damaged', 'id': selected['reference']['snapshot_id']})
        db.commit()
    response = authorize(client, selected, action='revoke', expected_revision=1)
    assert response.status_code == 200 and response.json()['authorization']['state'] == 'revoked'
    assert not provider.calls


def test_permission_can_be_revoked_after_model_configuration_is_removed(setup, monkeypatch):
    client, _database, provider = setup
    selected = granted(setup)
    previous = client.post('/v1/knowledge/text-embedding-authorizations/preview',
        json={'selection': selected}).json()
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.delenv('TI_OPENAI_API_KEY')
    response = authorize(client, selected, action='revoke', expected_revision=1, scope_hash=previous['scope_hash'])
    assert response.status_code == 200 and response.json()['authorization']['state'] == 'revoked'
    assert not provider.calls


@pytest.mark.parametrize('field,value', [('expected_revision', True), ('acknowledged', 1), ('acknowledged', False),
    ('privacy_class', 'restricted'), ('rights_basis', ' '), ('expires_at', '2020-01-01T00:00:00Z')])
def test_permission_input_is_strict_and_bounded(setup, field, value):
    client, database, provider = setup
    register_admin(client)
    selected = selection(client, database)
    assert authorize(client, selected, **{field: value}).status_code == 422
    assert not provider.calls


def test_expired_permission_refuses_current_plan(setup, monkeypatch):
    client, _database, provider = setup
    selected = granted(setup)
    assert authorize(client, selected, expected_revision=1,
        expires_at=(utcnow() + timedelta(minutes=1)).isoformat()).status_code == 200
    prepared = plan(client, selected).json()
    from tire_api import text_embeddings
    now = utcnow()
    monkeypatch.setattr(text_embeddings, 'utcnow', lambda: now + timedelta(minutes=2))
    assert build(client, prepared['id']).status_code == 403
    assert not provider.calls


def test_revocation_accepts_the_expired_license_metadata(setup):
    client, _database, provider = setup
    selected = granted(setup)
    response = authorize(client, selected, action='revoke', expected_revision=1,
        expires_at=(utcnow() - timedelta(minutes=1)).isoformat())
    assert response.status_code == 200 and response.json()['authorization']['state'] == 'revoked'
    assert not provider.calls


def test_grant_binds_the_recipient_scope_reviewed_by_the_caller(setup):
    client, database, provider = setup
    register_admin(client)
    selected = selection(client, database)
    response = authorize(client, selected, scope_hash='f' * 64)
    assert response.status_code == 409
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TextEmbeddingAuthorization)) == 0
    assert not provider.calls


def test_same_host_different_embedding_endpoints_have_distinct_text_caches(setup, monkeypatch):
    client, database, provider = setup
    monkeypatch.setenv('TI_EMBEDDINGS_BASE_URL', 'https://embedding-fixture.invalid/first/v1')
    selected = granted(setup)
    first = plan(client, selected).json()
    assert build(client, first['id']).json()['state'] == 'completed'
    monkeypatch.setenv('TI_EMBEDDINGS_BASE_URL', 'https://embedding-fixture.invalid/second/v1')
    assert authorize(client, selected).status_code == 200
    second = plan(client, selected).json()
    assert second['pending_chunks'] == 1
    assert build(client, second['id']).json()['state'] == 'completed'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EmbeddingCache)) == 2
    assert len(provider.calls) == 2


def verify_text_embedding_persistence(url, *, authenticate=register_admin):
    """Called only by the isolated PostgreSQL verifier, with real pgvector SQL."""
    checks = []
    with pytest.MonkeyPatch.context() as monkeypatch:
        settings(monkeypatch)
        app = create_app(url, FixtureRegistry())
        provider = SyntheticEmbeddings()
        app.state.embedding_adapter = provider
        with TestClient(app) as client:
            authenticate(client)
            selected = selection(client, app.state.database, source='text-embedding-fixture')
            assert authorize(client, selected).status_code == 200
            prepared = plan(client, selected)
            assert prepared.status_code == 200, prepared.text
            result = build(client, prepared.json()['id'])
            assert result.status_code == 200 and result.json()['state'] == 'completed', result.text
            checks.append('html_original_through_shared_plan_budget_ledger_and_pgvector')
            document, _state = indexed_document(client, pages=('PostgreSQL PDF acoustic 🛞',))
            item, = pdf_search(client, 'acoustic', document_id=document['id']).json()['items']
            pdf_selection = {'kind': 'document_text', 'reference': item['reference']}
            assert authorize(client, pdf_selection).status_code == 200
            prepared_pdf = plan(client, pdf_selection)
            assert prepared_pdf.status_code == 200, prepared_pdf.text
            pdf_run = build(client, prepared_pdf.json()['id'])
            assert pdf_run.status_code == 200 and pdf_run.json()['state'] == 'completed', pdf_run.text
            checks.append('pdf_page_original_recovery_through_dispatch_and_pgvector')
            assert len(provider.calls) == 2
            with app.state.database.sessions() as db:
                versions = db.execute(text('SELECT version FROM tire_schema_versions')).scalars().all()
                assert '035_text_embedding_authorizations' in versions
                rows = db.execute(text('SELECT c.id, c.text_contract, v.embedding::text, '
                    'v.embedding <=> CAST(:query AS vector) FROM embedding_cache c '
                    'JOIN embedding_vectors v ON v.cache_id = c.id WHERE c.text_contract = :contract '
                    'ORDER BY c.id'), {'query': '[1,0,0]', 'contract': TEXT_CONTRACT}).all()
                assert len(rows) == 2 and all(float(row[3]) == 0 for row in rows)
                vectors = [[row[0], row[1], row[2]] for row in rows]
                with pytest.raises(DBAPIError, match='text_embedding_authorization_immutable'):
                    db.execute(text('UPDATE text_embedding_authorizations SET revision = revision + 20'))
                db.rollback()
            checks.append('035_native_permissions_and_real_cosine_mirror')
            assert authorize(client, selected, action='revoke', expected_revision=1).status_code == 200
            assert plan(client, selected).status_code == 403
            assert len(provider.calls) == 2
            checks.append('revocation_blocks_new_plan_while_immutable_cache_is_preserved')
            checkpoint = {'source': selected, 'pdf': pdf_selection, 'pdf_run_id': pdf_run.json()['id'], 'vectors': vectors}
    return {'checks': checks, 'checkpoint': checkpoint, 'provider': 'synthetic_fixed_vectors'}


def assert_text_embedding_checkpoint(url, checkpoint, *, authenticate):
    with pytest.MonkeyPatch.context() as monkeypatch:
        settings(monkeypatch)
        app = create_app(url, FixtureRegistry())
        provider = SyntheticEmbeddings()
        app.state.embedding_adapter = provider
        with TestClient(app) as client:
            authenticate(client)
            assert plan(client, checkpoint['source']).status_code == 403
            prepared = plan(client, checkpoint['pdf'])
            assert prepared.status_code == 200 and prepared.json()['pending_chunks'] == 0, prepared.text
            response = build(client, prepared.json()['id'])
            assert response.status_code == 200 and response.json()['state'] == 'completed', response.text
            run = client.get(f"/v1/knowledge/embedding-runs/{checkpoint['pdf_run_id']}?mode=history")
            assert run.status_code == 200 and run.json()['state'] == 'completed', run.text
            with app.state.database.sessions() as db:
                rows = db.execute(text('SELECT c.id, c.text_contract, v.embedding::text '
                    'FROM embedding_cache c JOIN embedding_vectors v ON v.cache_id = c.id '
                    'WHERE c.text_contract = :contract AND c.id = ANY(:ids) ORDER BY c.id'),
                    {'contract': TEXT_CONTRACT, 'ids': [row[0] for row in checkpoint['vectors']]}).all()
                assert [list(row) for row in rows] == checkpoint['vectors']
                for statement in ('UPDATE text_embedding_authorizations SET revision = revision + 20',
                                  'DELETE FROM text_embedding_authorizations',
                                  'TRUNCATE TABLE text_embedding_authorizations'):
                    with pytest.raises(DBAPIError, match='text_embedding_authorization_immutable'):
                        db.execute(text(statement))
                    db.rollback()
            assert not provider.calls
