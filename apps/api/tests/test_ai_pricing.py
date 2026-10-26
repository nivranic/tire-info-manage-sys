"""Manual synthetic prices and explicit workload planning; never real billing."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import localcontext
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import inspect, select

from tire_api.ai_pricing import AIPricePlanningRequest, AIPriceVersionCreate, FORMULA
from tire_api.ai_pricing_models import AIPriceVersion
from tire_api.main import create_app

BASE = '/v1/ai/'
PASSWORD = 'synthetic-pricing-password'
PRICE = {'vendor_label': 'Synthetic manual vendor', 'provider': 'openai_chat', 'model': 'Exact-Model-v1',
         'currency': 'USD', 'input_per_million': '1.25', 'output_per_million': '2.5',
         'source_note': 'Synthetic project-authored price, not supplier verification',
         'source_url': 'https://example.invalid/prices',
         'effective_from': '2020-01-01T00:00:00Z', 'effective_until': '2040-01-01T00:00:00Z'}
PUBLIC_FIELDS = set(PRICE) | {'id', 'recorded_at', 'actor_user_id'}


def ok(response, status=200):
    assert response.status_code == status
    return response.json()


def post_price(client, body=None, key=None):
    return client.post(BASE + 'price-versions', json=body or deepcopy(PRICE),
                       headers={'Idempotency-Key': key or str(uuid4())})


def workload(identifier, **changes):
    return {'price_version_id': identifier, 'request_count': 2,
            'input_tokens_per_request': 1_000_000, 'output_tokens_per_request': 500_000, **changes}


def plan(client, *items, planned_for='2030-01-01T00:00:00Z'):
    return client.post(BASE + 'price-planning', json={'planned_for': planned_for, 'items': list(items)})


def business_state(database):
    with database.engine.connect() as connection:
        return {name: sorted((tuple(row) for row in connection.exec_driver_sql(
            'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
            for name in inspect(connection).get_table_names() if name not in {'users', 'local_sessions'}}


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    app = create_app('sqlite:///' + (tmp_path / 'pricing.sqlite').as_posix())
    with TestClient(app) as admin:
        admin_user = ok(admin.post('/v1/auth/register', json={'username': 'pricing-admin', 'password': PASSWORD}))['user']
        reader, anonymous = TestClient(app), TestClient(app)
        try:
            ok(reader.post('/v1/auth/register', json={'username': 'pricing-reader', 'password': PASSWORD}))
            yield app, admin, reader, anonymous, admin_user
        finally:
            reader.close()
            anonymous.close()


def test_valid_json_authentication_precedes_body_semantic_validation(case):
    _app, admin, reader, anonymous, _user = case
    for client in (anonymous, reader):
        assert client.post(BASE + 'price-versions', json={}).status_code == 403
    assert anonymous.get(BASE + 'price-versions?limit=0').status_code == 401
    assert anonymous.post(BASE + 'price-planning', json={}).status_code == 401
    assert admin.post(BASE + 'price-versions', json={}).status_code == 422
    assert reader.post(BASE + 'price-planning', json={}).status_code == 422


def test_create_replay_conflict_account_scope_and_public_fields(case):
    app, admin, reader, _anonymous, user = case
    key = str(uuid4())
    created = ok(post_price(admin, key=key))
    assert set(created) == PUBLIC_FIELDS
    assert created['actor_user_id'] == user['id']
    assert created['effective_from'] == PRICE['effective_from']
    assert created['recorded_at'].endswith('Z')
    assert ok(post_price(admin, key=key)) == created
    assert ok(post_price(admin, {**PRICE, 'vendor_label': '  ' + PRICE['vendor_label'] + '  ',
                                'effective_from': '2020-01-01T00:00:00.000000Z'}, key=key)) == created
    assert post_price(admin, {**PRICE, 'input_per_million': '2'}, key=key).status_code == 409
    assert ok(post_price(admin, key=key)) == created
    assert ok(reader.get(BASE + 'price-versions'))['items'] == [created]
    with app.state.database.sessions() as db:
        rows = db.scalars(select(AIPriceVersion)).all()
        assert len(rows) == 1 and rows[0].request_hash
        private_values = [rows[0].actor_session_id, rows[0].idempotency_key, rows[0].request_hash]
    serialized = post_price(admin, key=key).text
    assert all(value not in serialized for value in private_values)
    assert admin.patch(BASE + 'price-versions/' + created['id'], json=PRICE).status_code == 404
    assert admin.delete(BASE + 'price-versions/' + created['id']).status_code == 404
    reader_id = ok(reader.get('/v1/auth/me'))['user']['id']
    ok(admin.post('/v1/auth/users/' + reader_id + '/role', json={'is_admin': True}))
    other_actor = ok(post_price(reader, key=key))
    assert other_actor['id'] != created['id'] and other_actor['actor_user_id'] == reader_id


def test_concurrent_same_key_replays_one_version(case):
    app, admin, _reader, _anonymous, _user = case
    twins = [TestClient(app), TestClient(app)]
    key, barrier = str(uuid4()), Barrier(2)
    try:
        for client in twins:
            ok(client.post('/v1/auth/login', json={'username': 'pricing-admin', 'password': PASSWORD}))
        def create(client):
            barrier.wait(timeout=10)
            return ok(post_price(client, key=key))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, twins))
        assert results[0] == results[1]
        assert len(ok(admin.get(BASE + 'price-versions'))['items']) == 1
    finally:
        for client in twins:
            client.close()


@pytest.mark.parametrize('field,value', [
    ('input_per_million', 1), ('input_per_million', True), ('input_per_million', '-0'),
    ('input_per_million', ' 1'), ('input_per_million', '1 '), ('input_per_million', '+1'),
    ('input_per_million', '1e2'), ('input_per_million', 'NaN'), ('input_per_million', 'Infinity'),
    ('input_per_million', '01'), ('input_per_million', '.1'), ('input_per_million', '1.'),
    ('input_per_million', '1000000000'), ('input_per_million', '0.123456789'),
    ('output_per_million', '-1'), ('output_per_million', 1.5),
    ('currency', 'usd'), ('currency', 'US'), ('currency', 'USD '),
    ('model', ' Exact-Model-v1'), ('model', 'Exact-Model-v1 '), ('model', 'Exact-Model-v1\n'),
    ('model', 'a/b'), ('model', '模型'), ('model', 'x' * 121),
    ('effective_from', '2020-01-01'), ('effective_from', '2020-01-01T00:00Z'),
    ('effective_from', '2020-01-01T00:00:00+00:00'), ('effective_from', '2020-01-01T01:00:00+01:00'),
    ('effective_from', '2020-02-30T00:00:00Z'), ('effective_from', '2020-01-01T00:00:00.1234567Z'),
    ('effective_from', ' 2020-01-01T00:00:00Z'), ('effective_from', None),
    ('effective_until', '2020-01-01T00:00:00Z'), ('effective_until', '2019-12-31T23:59:59Z'),
    ('source_url', 'javascript:alert(1)'), ('source_url', '/prices'), ('source_url', 'https:///prices'),
    ('source_url', 'https://user:secret@example.invalid'), ('source_url', 'https://example.invalid\\prices'),
    ('source_url', 'https://example.invalid/\nsecret'), ('source_url', 'https://example.invalid:bad/'),
    ('source_note', ' '), ('vendor_label', ' '),
])
def test_price_dto_rejects_invalid_raw_values(field, value):
    with pytest.raises(ValidationError):
        AIPriceVersionCreate.model_validate({**PRICE, field: value})


def test_price_required_nullable_fields_closed_schema_and_canonical_times():
    for field in PRICE:
        body = deepcopy(PRICE)
        body.pop(field)
        with pytest.raises(ValidationError):
            AIPriceVersionCreate.model_validate(body)
    for field in ('actor_session_id', 'actor_user_id', 'recorded_at', 'id', 'idempotency_key', 'request_hash'):
        with pytest.raises(ValidationError):
            AIPriceVersionCreate.model_validate({**PRICE, field: 'forbidden'})
    dto = AIPriceVersionCreate.model_validate({**PRICE, 'vendor_label': '  vendor  ', 'source_note': ' note ',
        'source_url': None, 'effective_until': None, 'effective_from': '2020-01-01T00:00:00.1Z',
        'input_per_million': '999999999.99999999', 'output_per_million': '0'})
    assert dto.vendor_label == 'vendor' and dto.source_note == 'note'
    assert dto.effective_from == '2020-01-01T00:00:00.100000Z'


def test_validation_errors_never_echo_submitted_secrets_or_context(case):
    _app, admin, _reader, _anonymous, _user = case
    sentinel = 'SYNTHETIC_SECRET_DO_NOT_ECHO'
    invalid = [{**PRICE, 'source_url': 'https://user:' + sentinel + '@example.invalid'},
               {**PRICE, sentinel: sentinel}, {**PRICE, 'input_per_million': sentinel},
               {**PRICE, 'actor_session_id': sentinel}, {**PRICE, 'effective_from': sentinel}]
    for body in invalid:
        response = post_price(admin, body)
        assert response.status_code == 422
        assert sentinel not in response.text
        assert response.json() == {'detail': {'code': 'ai_price_invalid_request',
            'message': '费用规划请求格式不正确，请核对填写内容。'}}
    response = post_price(admin, key=sentinel)
    assert response.status_code == 422 and sentinel not in response.text
    response = admin.post(BASE + 'price-planning', json={'planned_for': sentinel, 'items': []})
    assert response.status_code == 422 and sentinel not in response.text


@pytest.mark.parametrize('field,value', [
    ('request_count', True), ('request_count', 1.0), ('request_count', '1'), ('request_count', 0),
    ('request_count', 1_000_001), ('input_tokens_per_request', False),
    ('input_tokens_per_request', -1), ('input_tokens_per_request', 100_000_001),
    ('output_tokens_per_request', 0.5), ('output_tokens_per_request', '0'),
    ('price_version_id', 'no-version'), ('price_version_id', ' ' + str(uuid4())),
])
def test_planning_dto_strict_integer_and_uuid_bounds(field, value):
    with pytest.raises(ValidationError):
        AIPricePlanningRequest.model_validate({'planned_for': '2030-01-01T00:00:00Z',
            'items': [workload(str(uuid4()), **{field: value})]})


def test_planning_exact_half_up_tiny_zero_and_no_business_writes(case):
    app, admin, reader, _anonymous, _user = case
    standard = ok(post_price(admin))
    tiny = ok(post_price(admin, {**PRICE, 'input_per_million': '0.00000001', 'output_per_million': '0'}))
    half = ok(post_price(admin, {**PRICE, 'input_per_million': '0.5', 'output_per_million': '0'}))
    zero = ok(post_price(admin, {**PRICE, 'input_per_million': '0', 'output_per_million': '0', 'currency': 'CNY'}))
    before = business_state(app.state.database)
    result = ok(plan(reader, workload(standard['id']), workload(tiny['id'], request_count=1,
        input_tokens_per_request=1, output_tokens_per_request=0), workload(half['id'], request_count=1,
        input_tokens_per_request=1, output_tokens_per_request=0), workload(zero['id'])))
    assert business_state(app.state.database) == before
    assert set(result) == {'planned_for', 'calculated_at', 'calculation_version', 'scale', 'rounding',
                           'items', 'exclusions', 'notice'}
    assert result['calculation_version'] == 'standard-text-v1'
    assert result['scale'] == 6 and result['rounding'] == 'ROUND_HALF_UP'
    assert result['exclusions'] == ['cached_input', 'tools', 'long_context', 'images_audio_video',
                                    'tax', 'fx', 'supplier_adjustments']
    assert [row['exact_total'] for row in result['items']] == ['5', '0.00000000000001', '0.0000005', '0']
    assert [row['rounded_total'] for row in result['items']] == ['5.000000', '0.000000', '0.000001', '0.000000']
    assert result['items'][0]['exact_input_total'] == '2.5'
    assert result['items'][0]['exact_output_total'] == '2.5'
    assert all(row['formula'] == FORMULA and set(row['price_version']) == PUBLIC_FIELDS for row in result['items'])
    assert result['items'][0]['price_version'] == standard


def test_decimal_precision_is_independent_of_ambient_context(case):
    _app, admin, _reader, _anonymous, _user = case
    version = ok(post_price(admin, {**PRICE, 'input_per_million': '999999999.99999999',
                                    'output_per_million': '999999999.99999999'}))
    # Direct call runs in this exact ambient context rather than another HTTP worker thread.
    from tire_api.ai_pricing import plan_prices
    payload = AIPricePlanningRequest.model_validate({'planned_for': '2030-01-01T00:00:00Z', 'items': [
        workload(version['id'], request_count=1_000_000, input_tokens_per_request=100_000_000,
                 output_tokens_per_request=100_000_000)]})
    with localcontext() as ambient:
        ambient.prec = 2
        with case[0].state.database.sessions() as db:
            result = plan_prices(db, payload)['items'][0]
        assert ambient.prec == 2
    assert result['exact_input_total'] == '99999999999999999'
    assert result['exact_output_total'] == '99999999999999999'
    assert result['exact_total'] == '199999999999999998'
    assert result['rounded_total'] == '199999999999999998.000000'


def test_time_intervals_historical_future_and_atomic_failure(case):
    app, admin, reader, _anonymous, _user = case
    version = ok(post_price(admin, {**PRICE, 'effective_from': '1900-01-01T00:00:00Z',
                                    'effective_until': '2100-01-01T00:00:00Z'}))
    item = workload(version['id'])
    assert plan(reader, item, planned_for='1900-01-01T00:00:00Z').status_code == 200
    assert plan(reader, item, planned_for='2099-12-31T23:59:59.999999Z').status_code == 200
    before = business_state(app.state.database)
    response = plan(reader, item, workload(str(uuid4())))
    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'ai_price_version_not_found'
    assert response.json()['detail']['item_index'] == 1
    assert 'items' not in response.json() and 'exact_total' not in response.text
    for when in ('1899-12-31T23:59:59Z', '2100-01-01T00:00:00Z'):
        response = plan(reader, item, planned_for=when)
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'ai_price_version_not_effective'
        assert response.json()['detail']['item_index'] == 0
    assert business_state(app.state.database) == before


def test_fifty_items_zero_tokens_embeddings_and_missing_items(case):
    _app, admin, reader, _anonymous, _user = case
    assert post_price(admin, {**PRICE, 'provider': 'openai_embeddings'}).status_code == 422
    version = ok(post_price(admin, {**PRICE, 'provider': 'openai_embeddings', 'output_per_million': '0.00000000'}))
    item = workload(version['id'], input_tokens_per_request=0, output_tokens_per_request=0)
    response = ok(plan(reader, *[item] * 50))
    assert len(response['items']) == 50
    assert all(row['exact_total'] == '0' for row in response['items'])
    assert plan(reader, *[item] * 51).status_code == 422
    assert plan(reader).status_code == 422
    assert plan(reader, {**item, 'output_tokens_per_request': 1}).json()['detail']['item_index'] == 0
    assert plan(reader, {**item, 'provider': 'openai_chat'}).status_code == 422


def test_pagination_keeps_old_versions_reachable_and_does_not_replace_selection(case):
    _app, admin, reader, _anonymous, _user = case
    assert ok(reader.get(BASE + 'price-versions')) == {
        'items': [], 'offset': 0, 'limit': 10, 'has_more': False, 'next_offset': None}
    created = [ok(post_price(admin, {**PRICE, 'input_per_million': str(index)})) for index in range(27)]
    seen, offset = [], 0
    while True:
        page = ok(reader.get(BASE + 'price-versions', params={'offset': offset, 'limit': 10}))
        seen.extend(row['id'] for row in page['items'])
        if not page['has_more']:
            assert page['next_offset'] is None
            break
        offset = page['next_offset']
    expected = [row['id'] for row in sorted(created, key=lambda row: (row['recorded_at'], row['id']), reverse=True)]
    assert seen == expected and len(set(seen)) == 27
    assert ok(plan(reader, workload(created[0]['id'])))['items'][0]['price_version'] == created[0]
    assert reader.get(BASE + 'price-versions?limit=26').status_code == 422
    assert reader.get(BASE + 'price-versions?offset=-1').status_code == 422
