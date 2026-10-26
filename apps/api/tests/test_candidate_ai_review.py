"""Independent R77 adversarial HTTP tests over owned synthetic R69 evidence.

Run only through a review harness that prebinds both database URLs and private
objects/bundles before collection. No professional test/material is seeded.
Expected safety outcomes are hand written; product projection/contract helpers
are never used to construct a model answer or an expected result.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest


_PRIVATE_ROOT = os.environ.get('R77_REVIEW_STORAGE_ROOT')
if not _PRIVATE_ROOT or os.environ.get('TIRE_DATABASE_URL') != os.environ.get('DATABASE_URL'):
    raise RuntimeError('r77_review_private_harness_required_before_application_import')
if not os.environ['TIRE_DATABASE_URL'].startswith('sqlite:///' + Path(_PRIVATE_ROOT).as_posix() + '/'):
    raise RuntimeError('r77_review_bootstrap_database_must_be_private')

from fastapi.testclient import TestClient
from admin_support import register_admin
from test_fitment_relations import (NoNetworkRegistry, decision as relation_decision,
    post as relation_post, seed_tire, seed_vehicle, tire_payload)
from tire_api.main import create_app


PURPOSE = 'candidate_spec_assistance@1'
DIMENSIONS = {'dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance'}
WEIGHTS = {'dry': 20, 'wet': 25, 'quiet': 20, 'comfort': 10, 'wear': 15, 'energy': 5, 'appearance': 5}
QUESTION = 'Compare these exact specification candidates; performance remains unknown.'
PREPARE = '/v1/ai/candidate-preparations'
SUBMIT = '/v1/ai/candidate-recommendations'


def ok(response, statuses=(200,)):
    assert response.status_code in statuses, (response.status_code, response.text)
    return response.json()


class ObservedAdapter:
    def __init__(self):
        self.calls = []
        self.raw = '{"decision":"abstain","selections":[],"uncertainty_codes":[]}'

    async def generate(self, config, body):
        self.calls.append(deepcopy(body))
        return {'text': self.raw, 'usage': {'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5},
            'provider_response_id': 'r77_independent_synthetic', 'error': None}


@pytest.fixture
def review_case(monkeypatch):
    storage = Path(_PRIVATE_ROOT) / uuid4().hex[:8]
    storage.mkdir(parents=True, exist_ok=False)
    database_url = 'sqlite:///' + (storage / 'p.db').as_posix()
    for name in list(os.environ):
        if name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_')) or name == 'DATABASE_URL' or name.lower().endswith('_proxy'):
            monkeypatch.delenv(name, raising=False)
    for name, value in {'TIRE_DATABASE_URL': database_url, 'DATABASE_URL': database_url,
        'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(storage / 'o'),
        'TI_PARSER_BUNDLE_ROOT': str(storage / 'b'), 'TI_AI_ENABLED': '1',
        'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0',
        'TI_AI_PROVIDER': 'openai_responses', 'TI_OPENAI_MODEL': 'synthetic-r77-review',
        'TI_OPENAI_API_KEY': secrets.token_urlsafe(18), 'TI_AI_ALLOW_PRIVATE': '1',
        'TI_AI_DAILY_REQUEST_LIMIT': '100', 'TI_AI_DAILY_TOKEN_LIMIT': '1000000'}.items():
        monkeypatch.setenv(name, value)
    app = create_app(database_url, NoNetworkRegistry())
    adapter = ObservedAdapter()
    app.state.ai_adapter = adapter
    with TestClient(app, backend_options={'loop_factory': __import__('asyncio').SelectorEventLoop}) as client:
        password = secrets.token_urlsafe(18)
        actor = register_admin(client, username='r77-review-owner', password=password)['user']
        session_id = client.cookies['tire_local_session']
        database = app.state.database
        vehicle = seed_vehicle(database, session_id)
        selections, relations = [], []
        for index in range(2):
            value = tire_payload(manufacturer_product_code='R77-OWNED-' + str(index))
            value['facts']['review_private_marker'] = 'R77_FACTS_MUST_NOT_BE_SENT'
            variant_id, snapshot_id, fact_id = seed_tire(database, session_id, value,
                source='synthetic-r77-review-source-' + str(index))
            selected = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle,
                'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front',
                'variant_id': variant_id, 'tire_snapshot_id': snapshot_id, 'fact_version_id': fact_id}
            created = ok(relation_post(client, relation_decision(client, selected)), (201,))['relation']
            reviewed = ok(relation_post(client, relation_decision(client, selected,
                'review', created['id'])), (201,))['relation']
            selections.append(selected)
            relations.append(reviewed)
        preference = ok(client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': WEIGHTS}))
        selection = {key: selections[0][key] for key in
            ('vehicle_id', 'vehicle_snapshot_id', 'trim_id', 'wheel_option_id', 'axle')}
        request = {'selection': selection, 'expected_preference_revision': preference['revision'],
            'expected_preference_fingerprint': preference['fingerprint'],
            'variant_ids': [row['variant_id'] for row in selections], 'question': QUESTION}

        def login_same_account(other):
            return other.post('/v1/auth/login', json={'username': 'r77-review-owner', 'password': password})

        yield SimpleNamespace(app=app, client=client, database=database, adapter=adapter,
            actor=actor, selections=selections, relations=relations, preference=preference,
            request=request, storage=storage, login_same_account=login_same_account)
    app.state.database.engine.dispose()


def prepare(case):
    return ok(case.client.post(PREPARE, json=case.request))


def authorization(case, preparation, dependency, *, action='grant', client=None, **changes):
    current = dependency['authorization']
    provider = preparation['provider']['provider'] if preparation['provider'] else 'openai_responses'
    payload = {'dependency_id': dependency['id'], 'provider': provider,
        'expected_revision': current['revision'] if current else 0, 'action': action,
        'acknowledged': True}
    if action == 'revoke':
        payload['revocation_note'] = 'Independent review revokes this exact declared use permission.'
    else:
        payload.update({
        'rights_holder': 'Project-owned synthetic R77 review fixture',
        'license_basis_url': 'https://fixture.invalid/project-owned-license',
        'license_basis_note': 'Owned synthetic bytes; permit this exact candidate specification projection only.',
        'license_evidence_sha256': hashlib.sha256(b'R77 owned synthetic permission evidence').hexdigest(),
        'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    payload.update(changes)
    return (client or case.client).post(PREPARE + '/' + preparation['preparation_id'] + '/authorizations', json=payload)


def licensed(case, *, omit=0):
    initial = prepare(case)
    assert initial['sendable'] is False
    assert initial['dependencies']
    for dependency in initial['dependencies'][:len(initial['dependencies']) - omit]:
        ok(authorization(case, initial, dependency), (200, 201))
    return prepare(case)


def choose_one(preparation, index=0):
    candidate = preparation['candidates'][index]
    assert candidate['reasons']
    return {'decision': 'choose', 'selections': [{'variant_id': candidate['variant_id'],
        'reason_ids': [candidate['reasons'][0]['id']]}], 'uncertainty_codes': []}


def submit(case, preparation, *, key=None, client=None, **changes):
    payload = {'preparation_id': preparation['preparation_id'],
        'consent_hash': preparation['consent_hash'] or '0' * 64,
        'allow_external_processing': True, **changes}
    return (client or case.client).post(SUBMIT, json=payload,
        headers={'Idempotency-Key': key or str(uuid4())})


def blocked(response, case, previous_calls=0):
    assert response.status_code in (401, 403, 404, 409, 422), (response.status_code, response.text)
    assert len(case.adapter.calls) == previous_calls


def dedicated_rejection(response, case, previous_calls=0):
    blocked(response, case, previous_calls)
    # A missing DTO field/query parameter must never count as proof that the
    # dedicated-route business fence rejected this candidate pack/request.
    detail = response.json().get('detail')
    assert isinstance(detail, dict), response.text
    assert detail.get('code') == 'candidate_ai_dedicated_route_required', response.text


def assert_minimal_actual_projection(case, preparation):
    # Read the actual dispatched wire body without invoking a product projection,
    # schema or hashing helper to generate expected fields or values.
    user = next(row for row in case.adapter.calls[0]['input'] if row['role'] == 'user')
    content = json.loads(user['content'])
    assert set(content) == {'question', 'untrusted_evidence_pack'}
    assert content['question'] == QUESTION
    outbound = content['untrusted_evidence_pack']
    assert set(outbound) == {'schema', 'purpose', 'selection', 'preference', 'candidates',
        'ranking', 'performance_score', 'performance_evidence'}
    assert outbound['schema'] == 'candidate-ai-outbound@1'
    assert outbound['purpose'] == PURPOSE
    assert outbound['selection'] == case.request['selection']
    assert outbound['preference']['weights'] == WEIGHTS
    assert outbound['ranking'] == 'not_computed' and outbound['performance_score'] is None
    assert outbound['performance_evidence'] == 'not_established'
    allowed_identity = {'brand', 'model', 'manufacturer_product_code', 'region', 'size',
        'load_index', 'speed_rating', 'xl', 'hl', 'oe_mark', 'acoustic_technology',
        'run_flat', 'gtin', 'technology_features', 'eprel_id', 'product_code_type'}
    allowed_requirements = {'size', 'load_index', 'speed_rating', 'manufacturer_product_code',
        'product_code_type', 'oe_mark', 'region', 'xl', 'hl', 'acoustic_technology', 'run_flat'}
    assert [row['variant_id'] for row in outbound['candidates']] == case.request['variant_ids']
    for candidate in outbound['candidates']:
        assert set(candidate) == {'variant_id', 'identity', 'relations', 'reasons', 'unknown_fields'}
        assert set(candidate['identity']) <= allowed_identity
        for relation in candidate['relations']:
            assert set(relation) == {'relation_id', 'revision_id', 'revision', 'selection',
                'checks', 'acknowledged_unknowns'}
            for check in relation['checks']:
                assert set(check) == {'field', 'status', 'vehicle_value', 'tire_value'}
                assert check['field'] in allowed_requirements
                assert check['status'] in {'match', 'unknown', 'not_declared'}
            # Region comes from the vehicle source even where the axle-level
            # requirement omits it. Verify that declared use binds that value.
            assert next(check['vehicle_value'] for check in relation['checks']
                if check['field'] == 'region') == 'CN'
    vehicle_permissions = [row for row in preparation['dependencies'] if row['source_kind'] == 'vehicle']
    assert vehicle_permissions
    assert all('/check_values/region' in row['fields'] for row in vehicle_permissions)


def test_missing_any_selected_source_permission_blocks_the_entire_group(review_case):
    preparation = licensed(review_case, omit=1)
    assert preparation['sendable'] is False
    assert preparation['consent_hash'] is None
    blocked(submit(review_case, preparation), review_case)


def test_user_external_processing_consent_cannot_replace_source_permission(review_case):
    preparation = prepare(review_case)
    assert preparation['sendable'] is False
    blocked(submit(review_case, preparation, allow_external_processing=True), review_case)


def test_grants_require_a_new_preparation_before_submission(review_case):
    old = prepare(review_case)
    for dependency in old['dependencies']:
        ok(authorization(review_case, old, dependency), (200, 201))
    blocked(submit(review_case, old), review_case)
    fresh = prepare(review_case)
    assert fresh['sendable'] is True
    assert fresh['preparation_id'] != old['preparation_id']


def test_revoke_then_identical_regrant_cannot_revive_old_consent(review_case):
    old = licensed(review_case)
    assert old['sendable'] is True
    dependency = old['dependencies'][0]
    ok(authorization(review_case, old, dependency, action='revoke'), (200, 201))
    revoked = prepare(review_case)
    current = next(row for row in revoked['dependencies'] if row['id'] == dependency['id'])
    ok(authorization(review_case, revoked, current), (200, 201))
    fresh = prepare(review_case)
    assert fresh['sendable'] is True
    assert fresh['fingerprint'] != old['fingerprint']
    blocked(submit(review_case, old), review_case)


def test_missing_personal_consent_cannot_use_a_fully_licensed_preparation(review_case):
    preparation = licensed(review_case)
    assert preparation['sendable'] is True
    blocked(submit(review_case, preparation, allow_external_processing=False), review_case)
    blocked(submit(review_case, preparation, consent_hash='0' * 64), review_case)


@pytest.mark.parametrize('name,value', [
    ('TI_OPENAI_MODEL', 'synthetic-other-model'), ('TI_AI_ALLOW_PRIVATE', '0'),
    ('TI_AI_MAX_OUTPUT_TOKENS', '1600'), ('TI_AI_DAILY_TOKEN_LIMIT', '999999'),
])
def test_configuration_change_after_preparation_makes_zero_model_calls(review_case, monkeypatch, name, value):
    preparation = licensed(review_case)
    assert preparation['sendable'] is True
    monkeypatch.setenv(name, value)
    blocked(submit(review_case, preparation), review_case)


@pytest.mark.parametrize('mutation', [
    'other_candidate_reason', 'unknown_variant', 'unknown_reason', 'duplicate_variant',
    'duplicate_reason', 'extra_fact', 'selection_free_text', 'empty_choose',
    'abstain_with_selection', 'unknown_decision', 'boolean_decision', 'unknown_uncertainty',
    'free_uncertainty', 'duplicate_top_key', 'duplicate_nested_key', 'nonfinite',
])
def test_malicious_model_json_is_rejected_after_the_real_provider_call(review_case, mutation):
    preparation = licensed(review_case)
    assert preparation['sendable'] is True
    answer = choose_one(preparation)
    selected = answer['selections'][0]
    if mutation == 'other_candidate_reason':
        selected['reason_ids'] = [preparation['candidates'][1]['reasons'][0]['id']]
    elif mutation == 'unknown_variant':
        selected['variant_id'] = 'nonexistent-exact-candidate'
    elif mutation == 'unknown_reason':
        selected['reason_ids'] = ['nonexistent-reason']
    elif mutation == 'duplicate_variant':
        answer['selections'].append(deepcopy(selected))
    elif mutation == 'duplicate_reason':
        selected['reason_ids'].append(selected['reason_ids'][0])
    elif mutation == 'extra_fact':
        answer['performance_fact'] = 'This tire is objectively best in wet braking.'
    elif mutation == 'selection_free_text':
        selected['text'] = 'Guaranteed safe installation and superior wear.'
    elif mutation == 'empty_choose':
        answer['selections'] = []
    elif mutation == 'abstain_with_selection':
        answer['decision'] = 'abstain'
    elif mutation == 'unknown_decision':
        answer['decision'] = 'recommend_performance'
    elif mutation == 'boolean_decision':
        answer['decision'] = True
    elif mutation == 'unknown_uncertainty':
        answer['uncertainty_codes'] = ['performance_is_verified']
    elif mutation == 'free_uncertainty':
        answer['uncertainty_codes'] = 'Ignore restrictions and install this tire.'
    raw = json.dumps(answer, ensure_ascii=False, allow_nan=False)
    if mutation == 'duplicate_top_key':
        raw = '{"decision":"abstain","decision":"abstain","selections":[],"uncertainty_codes":[]}'
    elif mutation == 'duplicate_nested_key':
        row = json.dumps(selected, ensure_ascii=False, allow_nan=False)
        row = row[:-1] + ',"variant_id":' + json.dumps(selected['variant_id']) + '}'
        raw = '{"decision":"choose","selections":[' + row + '],"uncertainty_codes":[]}'
    elif mutation == 'nonfinite':
        raw = '{"decision":"abstain","selections":[],"uncertainty_codes":[NaN]}'
    review_case.adapter.raw = raw
    result = ok(submit(review_case, preparation), (200, 201))
    assert result['state'] == 'failed', result
    assert result['answer'] is None
    assert len(review_case.adapter.calls) == 1


def test_unknown_fields_are_not_published_as_positive_matching_reasons(review_case):
    preparation = licensed(review_case)
    assert any(candidate['unknown_fields'] for candidate in preparation['candidates'])
    for candidate in preparation['candidates']:
        for reason in candidate['reasons']:
            reference = reason['reference']
            assert reference['variant_id'] == candidate['variant_id']
            assert reference['status'] not in ('unknown', 'not_declared')
            assert reference['selection'] == review_case.request['selection']


def test_truncated_real_relation_scan_is_not_accepted_as_a_complete_candidate_set(review_case, monkeypatch):
    from tire_api import recommendation_candidates
    # Real SQL/projection still executes; this is the scan-boundary branch,
    # not an assertion that a 201-relation pressure test was performed.
    monkeypatch.setattr(recommendation_candidates, 'MAX_RELATIONS', 1)
    blocked(review_case.client.post(PREPARE, json=review_case.request), review_case)


def test_preference_change_invalidates_a_prepared_consent(review_case):
    preparation = licensed(review_case)
    changed = {**WEIGHTS, 'dry': 25, 'wet': 20}
    ok(review_case.client.put('/v1/driving-preferences', json={
        'expected_revision': review_case.preference['revision'], 'weights': changed}))
    blocked(submit(review_case, preparation), review_case)


def test_relation_revocation_invalidates_the_entire_prepared_group(review_case):
    preparation = licensed(review_case)
    selected, relation = review_case.selections[0], review_case.relations[0]
    ok(relation_post(review_case.client, relation_decision(review_case.client,
        selected, 'revoke', relation['id'])), (201,))
    blocked(submit(review_case, preparation), review_case)


def test_private_raw_evidence_corruption_cannot_be_hidden_by_a_stable_candidate_id(review_case):
    preparation = licensed(review_case)
    from sqlalchemy import text
    with review_case.database.engine.begin() as connection:
        connection.execute(text('UPDATE snapshots SET body = body || :suffix WHERE id = :id'),
            {'suffix': ' R77_PRIVATE_CORRUPTION', 'id': review_case.selections[0]['tire_snapshot_id']})
    blocked(submit(review_case, preparation), review_case)


def test_exact_identity_corruption_invalidates_a_preparation(review_case):
    preparation = licensed(review_case)
    from sqlalchemy import select, update
    from tire_api.identity_contract_models import VariantIdentityBinding
    # Simulate storage corruption only inside this GUID's private database.
    # Ordinary ORM mutation is separately prevented by append-only guards.
    with review_case.database.engine.begin() as connection:
        row_id = review_case.selections[0]['variant_id']
        identity = connection.scalar(select(VariantIdentityBinding.current_identity)
            .where(VariantIdentityBinding.variant_id == row_id))
        connection.execute(update(VariantIdentityBinding).where(VariantIdentityBinding.variant_id == row_id)
            .values(current_identity={**identity, 'load_index': '999'}))
    response = submit(review_case, preparation)
    assert response.status_code == 503, response.text
    assert response.json()['detail']['code'] == 'identity_binding_integrity_failed'
    assert not review_case.adapter.calls


def test_expired_preparation_cannot_prevent_revoking_an_existing_grant(review_case, monkeypatch):
    preparation = licensed(review_case)
    from tire_api import candidate_ai
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setattr(candidate_ai, 'utcnow', lambda: later)
    result = ok(authorization(review_case, preparation, preparation['dependencies'][0], action='revoke'), (200, 201))
    assert result['state'] == 'revoked'
    assert not review_case.adapter.calls


def test_unreadable_source_does_not_prevent_revoking_an_existing_grant(review_case):
    preparation = licensed(review_case)
    from sqlalchemy import text
    with review_case.database.engine.begin() as connection:
        connection.execute(text('UPDATE snapshots SET body = body || :suffix WHERE id = :id'),
            {'suffix': ' R77_PRIVATE_CORRUPTION', 'id': review_case.selections[0]['tire_snapshot_id']})
    dependency = next(row for row in preparation['dependencies']
        if row['snapshot_id'] == review_case.selections[0]['tire_snapshot_id'])
    result = ok(authorization(review_case, preparation, dependency, action='revoke'), (200, 201))
    assert result['state'] == 'revoked'
    assert not review_case.adapter.calls


@pytest.mark.parametrize('url', [
    'https://user:synthetic-password@fixture.invalid/license',
    'https://fixture.invalid/license?access_token=synthetic-not-a-real-secret',
])
def test_license_basis_url_cannot_carry_credentials_or_identity_parameters(review_case, url):
    preparation = prepare(review_case)
    blocked(authorization(review_case, preparation, preparation['dependencies'][0],
        license_basis_url=url), review_case)


def test_stale_authorization_revision_does_not_overwrite_a_grant(review_case):
    preparation = prepare(review_case)
    dependency = preparation['dependencies'][0]
    first = ok(authorization(review_case, preparation, dependency), (200, 201))
    assert first['revision'] == 1
    blocked(authorization(review_case, preparation, dependency), review_case)
    fresh = prepare(review_case)
    head = next(row['authorization'] for row in fresh['dependencies'] if row['id'] == dependency['id'])
    assert head['revision'] == 1
    assert head['revision_id'] == first['revision_id']


def test_successful_choice_is_not_a_performance_rank_or_a_license_export(review_case):
    preparation = licensed(review_case)
    assert preparation['sendable'] is True
    review_case.adapter.raw = json.dumps(choose_one(preparation), allow_nan=False)
    result = ok(submit(review_case, preparation), (200, 201))
    assert result['state'] == 'completed'
    assert result['current'] is False
    answer = result['answer']
    first, second = [row['variant_id'] for row in review_case.selections]
    assert [row['variant_id'] for row in answer['selections']] == [first]
    assert answer['not_selected_variant_ids'] == [second]
    assert answer['ranking'] == 'not_computed'
    assert answer['performance_score'] is None
    assert answer['performance_evidence'] == 'not_established'
    assert {'performance_evidence_unavailable', 'installation_safety_unestablished',
        'official_oe_unestablished', 'preference_performance_unestablished'} <= {
        row['code'] for row in answer['uncertainty']}
    assert len(review_case.adapter.calls) == 1
    assert_minimal_actual_projection(review_case, preparation)
    actual_body = json.dumps(review_case.adapter.calls[0], ensure_ascii=False, allow_nan=False)
    assert PURPOSE in actual_body
    for forbidden in ('R77_FACTS_MUST_NOT_BE_SENT', 'https://fixture.invalid/',
        '"source_url"', '"facts"', '"operator"', '"provenance"'):
        assert forbidden not in actual_body
    response = review_case.client.post('/v1/reports', json={'mode': 'history',
        'pack_id': result['pack_id'], 'analysis_id': result['id'], 'title': 'Forbidden candidate export'},
        headers={'Idempotency-Key': str(uuid4())})
    dedicated_rejection(response, review_case, previous_calls=1)
    unchanged = ok(review_case.client.post('/v1/fitment-candidates/preview?mode=history', json={key:
        value for key, value in review_case.request.items() if key not in {'variant_ids', 'question'}}))
    assert {row['variant_id'] for row in unchanged['items']} == {first, second}
    assert unchanged['ranking'] == 'not_computed' and unchanged['performance_score'] is None
    assert {row['dimension'] for row in unchanged['research_focus']} == DIMENSIONS
    assert all(row['evidence_status'] == 'exact_sku_performance_not_established'
        for row in unchanged['research_focus'])


def test_same_key_only_replays_and_another_key_cannot_consume_the_preparation(review_case):
    preparation = licensed(review_case)
    review_case.adapter.raw = json.dumps(choose_one(preparation), allow_nan=False)
    key = str(uuid4())
    first = ok(submit(review_case, preparation, key=key), (200, 201))
    replay = ok(submit(review_case, preparation, key=key), (200, 201))
    assert replay['id'] == first['id'] and replay['answer'] == first['answer']
    assert len(review_case.adapter.calls) == 1
    blocked(submit(review_case, preparation), review_case, previous_calls=1)
    blocked(submit(review_case, preparation, key=key, consent_hash='0' * 64), review_case, previous_calls=1)


@pytest.mark.parametrize('path,kind', [
    ('/v1/ai/analyses', 'analysis'), ('/v1/ai/analysis-streams', 'analysis'),
    ('/v1/ai/rule-drafts', 'rule'), ('/v1/reports', 'report'),
])
def test_generic_write_paths_cannot_consume_a_candidate_pack(review_case, path, kind):
    preparation = licensed(review_case)
    payload = {'pack_id': preparation['pack_id'], 'allow_external_processing': True}
    if kind == 'analysis':
        payload['question'] = QUESTION
    elif kind == 'report':
        payload = {'mode': 'history', 'pack_id': preparation['pack_id'], 'title': 'Forbidden C report'}
    dedicated_rejection(review_case.client.post(path, json=payload,
        headers={'Idempotency-Key': str(uuid4())}), review_case)


def test_generic_reads_and_history_cannot_expose_a_candidate_result(review_case):
    preparation = licensed(review_case)
    review_case.adapter.raw = json.dumps(choose_one(preparation), allow_nan=False)
    key = str(uuid4())
    result = ok(submit(review_case, preparation, key=key), (200, 201))
    for path in ('/v1/ai/evidence-packs/' + preparation['pack_id'] + '?mode=history',
        '/v1/ai/analyses/' + result['id'] + '?mode=history',
        '/v1/ai/analysis-streams/' + result['id'] + '?mode=history',
        '/v1/ai/analysis-streams/lookup?mode=history&idempotency_key=' + key,
        '/v1/ai/analysis-streams/' + result['id'] + '/events',
        '/v1/ai/analysis-streams/' + result['id'] + '/events/stream',
        '/v1/ai/rule-drafts/' + result['id'] + '?mode=history'):
        dedicated_rejection(review_case.client.get(path), review_case, previous_calls=1)
    for path in ('/v1/ai/analyses', '/v1/ai/rule-drafts', '/v1/reports'):
        history = ok(review_case.client.get(path + '?mode=history'))
        assert result['id'] not in json.dumps(history, ensure_ascii=False)
    for path in ('/v1/ai/analyses', '/v1/ai/analysis-streams', '/v1/ai/rule-drafts'):
        payload = {'pack_id': preparation['pack_id'], 'allow_external_processing': True}
        if path != '/v1/ai/rule-drafts':
            payload['question'] = QUESTION
        dedicated_rejection(review_case.client.post(path, json=payload,
            headers={'Idempotency-Key': key}), review_case, previous_calls=1)
    dedicated = ok(review_case.client.get(SUBMIT + '/' + result['id'] + '?mode=history'))
    assert dedicated['id'] == result['id'] and dedicated['current'] is False
    assert len(review_case.adapter.calls) == 1


@pytest.mark.parametrize('erase_evidence', [False, True])
def test_a_forged_generic_purpose_cannot_override_structural_candidate_ownership(review_case, erase_evidence):
    preparation = licensed(review_case)
    from sqlalchemy import select, update
    from tire_api.ai_models import AIEvidencePack
    with review_case.database.engine.begin() as connection:
        row_id = preparation['pack_id']
        payload = connection.scalar(select(AIEvidencePack.payload).where(AIEvidencePack.id == row_id))
        payload = {**payload, 'purpose': 'analysis'}
        if erase_evidence:
            payload['evidence'] = []
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        connection.execute(update(AIEvidencePack).where(AIEvidencePack.id == row_id)
            .values(payload=payload, fingerprint=fingerprint))
    dedicated_rejection(review_case.client.post('/v1/ai/analyses', json={
        'pack_id': preparation['pack_id'], 'question': QUESTION, 'allow_external_processing': True},
        headers={'Idempotency-Key': str(uuid4())}), review_case)
    dedicated_rejection(review_case.client.get('/v1/ai/evidence-packs/' +
        preparation['pack_id'] + '?mode=history'), review_case)
    from fastapi import HTTPException
    from tire_api.ai_analysis import grounded_answer
    with review_case.database.sessions() as db:
        attached = db.get(AIEvidencePack, preparation['pack_id'])
        with pytest.raises(HTTPException) as rejected:
            grounded_answer('{"claims":[],"uncertainty":""}', attached)
        assert rejected.value.detail['code'] == 'candidate_ai_dedicated_route_required'


def test_generic_report_routes_filter_a_preexisting_record_that_references_a_candidate_pack(review_case):
    preparation = licensed(review_case)
    from tire_api.report_models import ResearchReport, ResearchReportRevision
    report_id = uuid4().hex
    body = {'evidence': [], 'r77_private_forged_historical_record': True}
    body_hash = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    # Deliberately seed a historic-looking record below the HTTP create gate.
    # Every reader/export must still discriminate its candidate pack by DB key.
    with review_case.database.sessions() as db:
        db.add(ResearchReport(id=report_id,
            actor_session_id=review_case.client.cookies['tire_local_session'],
            idempotency_key=str(uuid4()), request_hash='0' * 64,
            pack_id=preparation['pack_id'], analysis_id=None, privacy_class='private',
            body=body, body_hash=body_hash))
        db.flush()
        db.add(ResearchReportRevision(report_id=report_id, revision=1,
            title='R77 forged historic candidate report', notes='', archived=False, operation='create'))
        db.commit()
    history = ok(review_case.client.get('/v1/reports?mode=history'))
    assert history['total'] == 0 and history['items'] == []
    dedicated_rejection(review_case.client.get('/v1/reports/' + report_id + '?mode=history'), review_case)
    dedicated_rejection(review_case.client.post('/v1/reports/' + report_id + '/exports',
        json={'revision': 1, 'format': 'markdown'}), review_case)
    dedicated_rejection(review_case.client.get('/v1/reports/' + report_id +
        '/exports/nonexistent/content?mode=history&revision=1'), review_case)


def test_revoked_use_permission_preserves_a_frozen_history_without_another_provider_call(review_case):
    preparation = licensed(review_case)
    review_case.adapter.raw = json.dumps(choose_one(preparation), allow_nan=False)
    key = str(uuid4())
    result = ok(submit(review_case, preparation, key=key), (200, 201))
    ok(authorization(review_case, preparation, preparation['dependencies'][0], action='revoke'), (200, 201))
    for path in (SUBMIT + '/' + result['id'] + '?mode=history', SUBMIT + '?mode=history&key=' + key):
        history = ok(review_case.client.get(path))
        assert history['id'] == result['id'] and history['answer'] == result['answer']
        assert history['current'] is False
        assert history['current_status']['state'] == 'stale'
    assert len(review_case.adapter.calls) == 1


@pytest.mark.parametrize('corruption', ['completion_reason_text', 'completion_reason_reference',
    'completion_extra_fact', 'request_body_hash', 'request_consent_hash', 'orphan_request_without_claim'])
def test_candidate_history_cannot_publish_forged_or_unbound_stored_advice(review_case, corruption):
    preparation = licensed(review_case)
    review_case.adapter.raw = json.dumps(choose_one(preparation), allow_nan=False)
    key = str(uuid4())
    result = ok(submit(review_case, preparation, key=key), (200, 201))
    from sqlalchemy import select, update
    from tire_api.ai_models import AICompletion, AIRequest
    request_id = result['id']
    if corruption.startswith('completion_'):
        with review_case.database.engine.begin() as connection:
            answer = deepcopy(connection.scalar(select(AICompletion.answer)
                .where(AICompletion.request_id == request_id)))
            if corruption == 'completion_reason_text':
                answer['selections'][0]['reasons'][0]['text'] = 'R77_FORGED_PERFORMANCE: best wet braking and guaranteed safe installation.'
            elif corruption == 'completion_reason_reference':
                answer['selections'][0]['reasons'][0]['reference']['value'] = 'R77_FORGED_PERFORMANCE'
            else:
                answer['performance_fact'] = 'R77_FORGED_PERFORMANCE'
            connection.execute(update(AICompletion).where(AICompletion.request_id == request_id)
                .values(answer=answer))
    elif corruption.startswith('request_'):
        with review_case.database.engine.begin() as connection:
            contract = deepcopy(connection.scalar(select(AIRequest.request_contract)
                .where(AIRequest.id == request_id)))
            contract['body_hash' if corruption == 'request_body_hash' else 'consent_hash'] = '0' * 64
            connection.execute(update(AIRequest).where(AIRequest.id == request_id).values(request_contract=contract))
    else:
        # A historic-looking row without reserve/claim must not become advice
        # merely because it points at a valid preparation's pack.
        with review_case.database.sessions() as db:
            original = db.get(AIRequest, result['id'])
            values = {column.name: deepcopy(getattr(original, column.name))
                for column in AIRequest.__table__.columns}
            request_id, key = uuid4().hex, str(uuid4())
            values.update(id=request_id, idempotency_key=key)
            db.add(AIRequest(**values))
            db.flush()
            original_completion = db.get(AICompletion, result['id'])
            values = {column.name: deepcopy(getattr(original_completion, column.name))
                for column in AICompletion.__table__.columns}
            values['request_id'] = request_id
            db.add(AICompletion(**values))
            db.commit()
    for path in (SUBMIT + '/' + request_id + '?mode=history', SUBMIT + '?mode=history&key=' + key):
        response = review_case.client.get(path)
        assert response.status_code in (409, 422), (corruption, response.status_code, response.text)
        assert 'R77_FORGED_PERFORMANCE' not in response.text
    response = submit(review_case, preparation, key=key)
    assert response.status_code in (409, 422), response.text
    assert 'R77_FORGED_PERFORMANCE' not in response.text
    assert len(review_case.adapter.calls) == 1


def test_same_account_new_session_uses_dedicated_reads_but_cannot_fall_back_to_generic_analysis(review_case):
    preparation = licensed(review_case)
    review_case.adapter.raw = json.dumps(choose_one(preparation), allow_nan=False)
    result = ok(submit(review_case, preparation), (200, 201))
    other = TestClient(review_case.app)
    try:
        ok(review_case.login_same_account(other))
        dedicated = ok(other.get(SUBMIT + '/' + result['id'] + '?mode=history'))
        assert dedicated['id'] == result['id'] and dedicated['current'] is False
        dedicated_rejection(other.get('/v1/ai/evidence-packs/' + preparation['pack_id'] + '?mode=history'),
            review_case, previous_calls=1)
        dedicated_rejection(other.post('/v1/ai/analyses', json={'pack_id': preparation['pack_id'],
            'question': QUESTION, 'allow_external_processing': True},
            headers={'Idempotency-Key': str(uuid4())}), review_case, previous_calls=1)
    finally:
        other.close()


def test_another_account_cannot_claim_a_preparation_or_change_its_permissions(review_case):
    preparation = licensed(review_case)
    other = TestClient(review_case.app)
    try:
        ok(other.post('/v1/auth/register', json={'username': 'r77-independent-other',
            'password': secrets.token_urlsafe(18)}))
        blocked(submit(review_case, preparation, client=other), review_case)
        blocked(authorization(review_case, preparation, preparation['dependencies'][0],
            client=other, action='revoke'), review_case)
    finally:
        other.close()


def test_reservation_followed_by_revocation_makes_zero_provider_calls_and_has_a_terminal_completion(review_case, monkeypatch):
    preparation = licensed(review_case)
    from tire_api import ai_execution
    original_execute = ai_execution.execute_response
    observed = []

    def revoke_before_actual_adapter(db, app, row, config, body, validator):
        # Actual reserve_response has committed. The real authorization route
        # writes a new revision before the unmodified execution/dispatch fence.
        assert row.pack_id == preparation['pack_id']
        observed.append(ok(authorization(review_case, preparation,
            preparation['dependencies'][0], action='revoke'), (200, 201)))
        return original_execute(db, app, row, config, body, validator)

    monkeypatch.setattr(ai_execution, 'execute_response', revoke_before_actual_adapter)
    key = str(uuid4())
    result = ok(submit(review_case, preparation, key=key), (200, 201))
    assert observed and observed[0]['state'] == 'revoked'
    assert result['state'] == 'failed' and result['answer'] is None
    assert result['error_code']
    assert not review_case.adapter.calls
    replay = ok(submit(review_case, preparation, key=key), (200, 201))
    assert replay['id'] == result['id'] and replay['state'] == 'failed'
    assert not review_case.adapter.calls
    status = ok(review_case.client.get('/v1/ai/status'))
    assert status['budget']['has_pending_request'] is False


def test_source_permission_does_not_follow_an_openai_compatible_provider_to_another_host(review_case, monkeypatch):
    monkeypatch.setenv('TI_AI_PROVIDER', 'openai_chat')
    monkeypatch.setenv('TI_CHAT_MODEL', 'synthetic-r77-compatible')
    monkeypatch.setenv('TI_CHAT_API_KEY', secrets.token_urlsafe(18))
    monkeypatch.setenv('TI_CHAT_BASE_URL', 'https://r77-first.invalid/v1')
    original = licensed(review_case)
    assert original['sendable'] is True
    monkeypatch.setenv('TI_CHAT_BASE_URL', 'https://r77-second.invalid/v1')
    changed_host = prepare(review_case)
    assert changed_host['sendable'] is False
    assert changed_host['consent_hash'] is None
    blocked(submit(review_case, changed_host), review_case)
    blocked(submit(review_case, original), review_case)


@pytest.mark.parametrize('fault', ['expired', 'source_corrupt', 'owner_deleted', 'provider_disabled'])
def test_another_admin_can_revoke_and_is_recorded_as_the_executing_actor(review_case, monkeypatch, fault):
    preparation = licensed(review_case)
    other = TestClient(review_case.app)
    try:
        user = ok(other.post('/v1/auth/register', json={'username': 'r77-review-other-admin',
            'password': secrets.token_urlsafe(18)}))['user']
        ok(review_case.client.post('/v1/auth/users/' + user['id'] + '/role', json={'is_admin': True}))
        if fault == 'expired':
            from tire_api import candidate_ai
            later = datetime.now(timezone.utc) + timedelta(hours=2)
            monkeypatch.setattr(candidate_ai, 'utcnow', lambda: later)
        elif fault == 'source_corrupt':
            from sqlalchemy import text
            with review_case.database.engine.begin() as connection:
                connection.execute(text('UPDATE snapshots SET body = body || :suffix WHERE id = :id'),
                    {'suffix': ' R77_PRIVATE_CORRUPTION', 'id': review_case.selections[0]['tire_snapshot_id']})
        elif fault == 'owner_deleted':
            deleted = other.delete('/v1/auth/users/' + review_case.actor['id'])
            assert deleted.status_code in (200, 204), deleted.text
        else:
            monkeypatch.setenv('TI_AI_ENABLED', '0')
        result = ok(authorization(review_case, preparation, preparation['dependencies'][0],
            action='revoke', client=other), (200, 201))
        assert result['state'] == 'revoked'
        from tire_api.candidate_ai_models import CandidateAIAuthorization
        with review_case.database.sessions() as db:
            revision = db.get(CandidateAIAuthorization, result['revision_id'])
            assert revision.actor_user_id == user['id']
            assert revision.actor_user_id != review_case.actor['id']
        assert not review_case.adapter.calls
    finally:
        other.close()
