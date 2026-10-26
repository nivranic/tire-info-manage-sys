"""R119 HTTP contract with synthetic local evidence, never a human Golden claim.

Expected values below are authored independently of the product comparison code.
The canonical regression runner supplies a private SQLite and object-store slot.
"""
from copy import deepcopy
import base64
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from tire_api.db import EvidenceDocument, EvidenceObject
from tire_api.documents import document_metadata
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.test_event_golden_checks import compare_identities, compare_values
from tire_api.test_event_golden_models import (TestEventGoldenCase, TestEventGoldenCaseRevision,
    TestEventGoldenCaseReview, TestEventGoldenSetRevision)
from tire_api.test_events import TireTestEvent, TireTestRevision
from test_test_sku_bridge_review import (case as bridge_case, decision as bridge_decision,
    link_view as bridge_link_view, reviewed as reviewed_bridge, submit as submit_bridge,
    synthetic_pdf)


BASE = '/v1/test-event-golden'
PASSWORD = 'Synthetic-R119-private-contract-password'

# Deliberately literal, including optional/null/default fields. In particular, neither
# a server response nor the production comparison helper supplies this expected value.
EVENT = {
    'title': 'Synthetic wet braking comparison', 'organization': 'Fixture Test Lab',
    'relationship': 'independent', 'publication_date': '2026-09-01',
    'source_url': 'https://fixture.example/test-2026',
    'rights_basis': 'Project-authored synthetic data', 'tested_size': '225/50R17',
    'vehicle': None, 'surface': 'Fixture wet asphalt',
    'conditions': 'Synthetic 80 to 20 km/h wet braking; temperature not reported',
    'coverage': 'selected_results', 'reported_participants': 20,
    'participants': [
        {'key': 'a', 'brand': 'Fixture A', 'model': 'Synthetic tire', 'source_designation': ''},
        {'key': 'b', 'brand': 'Fixture B', 'model': 'Synthetic tire', 'source_designation': ''},
    ],
    'metrics': [
        {'key': 'wet', 'label': 'Wet braking', 'unit': 'm',
         'protocol': '80 to 20 km/h, wet asphalt', 'direction': 'lower'},
        {'key': 'noise', 'label': 'Noise', 'unit': 'dB',
         'protocol': 'Synthetic method; speed not reported', 'direction': 'unspecified'},
    ],
    'measurements': [
        {'participant_key': 'a', 'metric_key': 'wet', 'raw_value': '38.00', 'source_rank': 3,
         'evidence_span': 'Fixture A: 38.00 m, rank 3', 'evidence_locator': 'Synthetic table, wet row A'},
        {'participant_key': 'b', 'metric_key': 'wet', 'raw_value': '40.0', 'source_rank': 5,
         'evidence_span': 'Fixture B: 40.0 m, rank 5', 'evidence_locator': 'Synthetic table, wet row B'},
        {'participant_key': 'a', 'metric_key': 'noise', 'raw_value': '70', 'source_rank': None,
         'evidence_span': 'Fixture A: 70 dB', 'evidence_locator': 'Synthetic noise row A'},
    ],
}


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def register(client, name):
    response = client.post('/v1/auth/register', json={'username': name, 'password': PASSWORD})
    assert response.status_code == 200
    return response.json()['user']


def signed(**changes):
    return {'operator': 'Synthetic R119 operator',
            'reason': 'Review synthetic local contract evidence only', **changes}


def post(client, route, body, *, key=None):
    return client.post(BASE + route, json=body, headers={'Idempotency-Key': key or str(uuid4())})


def counts(database):
    models = (TestEventGoldenCase, TestEventGoldenCaseRevision, TestEventGoldenCaseReview,
              TestEventGoldenSetRevision, TireTestEvent, TireTestRevision, EvidenceDocument)
    with database.sessions() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in models)


def business_state(database):
    """Exact persisted rows, including audit/bridge rows, not just row counts."""
    with database.engine.connect() as connection:
        names = [name for name in inspect(connection).get_table_names()
                 if name not in {'users', 'local_sessions'} and not name.startswith('sqlite_')]
        return {name: sorted((tuple(row) for row in connection.exec_driver_sql(
            'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr) for name in names}


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    app = create_app('sqlite:///' + (tmp_path / 'r119.sqlite').as_posix())
    with TestClient(app) as author:
        author_registration = author.post('/v1/auth/register',
            json={'username': 'r119-author', 'password': PASSWORD})
        assert author_registration.status_code == 200
        author_user = author_registration.json()['user']  # first account is admin
        reviewer, observer = TestClient(app), TestClient(app)
        try:
            reviewer_registration = reviewer.post('/v1/auth/register',
                json={'username': 'r119-reviewer', 'password': PASSWORD})
            assert reviewer_registration.status_code == 200
            reviewer_user = reviewer_registration.json()['user']
            observer_registration = observer.post('/v1/auth/register',
                json={'username': 'r119-observer', 'password': PASSWORD})
            assert observer_registration.status_code == 200
            promotion = author.post('/v1/auth/users/' + reviewer_user['id'] + '/role',
                                    json={'is_admin': True})
            assert promotion.status_code == 200
            event_response = author.post('/v1/test-events', json=signed(event=deepcopy(EVENT)))
            assert event_response.status_code == 201
            event = event_response.json()
            assert event['event'] == EVENT
            lines = ['SYNTHETIC MATERIAL - NOT A REAL TEST REPORT',
                     'Synthetic wet braking comparison', 'Fixture A: 38.00 m, rank 3']
            pdf = synthetic_pdf(lines)
            metadata = {'title': 'Project-authored synthetic test report',
                        'source_url': EVENT['source_url'], 'operator': 'Synthetic fixture author',
                        'rights_basis': 'Project-owned synthetic fixture only'}
            upload_response = author.post('/v1/documents', content=pdf,
                headers={'Content-Type': 'application/pdf', 'X-Evidence-Metadata':
                    base64.b64encode(json.dumps(metadata).encode()).decode()})
            if upload_response.status_code != 201:
                # Only one fixed stage/status/known code, never the response body,
                # credentials, raw PDF, arbitrary error text or filesystem path.
                known = {
                    '目前仅接收 PDF 原始文档': 'content_type',
                    '请提供有界的文档说明与保存授权依据': 'metadata_header',
                    '文档说明、署名或保存授权依据无效': 'metadata_invalid',
                    '原始文档不得超过 8 MiB': 'size_limit',
                    '文件没有 PDF 标识；原文未保存': 'pdf_header',
                    '原文存储未完成，未创建文档记录': 'object_store',
                }
                try:
                    detail = upload_response.json().get('detail')
                except (ValueError, TypeError, AttributeError):
                    detail = None
                (tmp_path / 'r119-upload-diagnostic.json').write_text(json.dumps({
                    'stage': 'pdf_upload', 'status': upload_response.status_code,
                    'known_detail': known.get(detail, 'unknown') if isinstance(detail, str) else 'unknown',
                }), encoding='utf-8')
            assert upload_response.status_code == 201
            document = upload_response.json()
            with app.state.database.sessions() as db:
                row = db.get(EvidenceDocument, document['id'])
                obj = db.get(EvidenceObject, row.raw_hash)
                frozen_metadata = {**document_metadata(row, obj.byte_count),
                                   'actor_session_id': row.actor_session_id}
                material = {
                    'document_id': row.id, 'expected_raw_hash': row.raw_hash,
                    'expected_metadata_hash': digest(frozen_metadata),
                    'event_locator': {'page': 1, 'region': 'synthetic title', 'quote': lines[1]},
                    'participant_locator': {'page': 1, 'region': 'synthetic row', 'quote': lines[2]},
                    'rights': {'rights_holder': 'Project synthetic fixture authors',
                               'basis': 'Project-owned synthetic fixture only',
                               'store_original': True, 'workspace_reopen': True,
                               'quote_identifiers': True, 'quote_test_results': True},
                }
            yield {'app': app, 'database': app.state.database, 'author': author,
                   'reviewer': reviewer, 'observer': observer, 'author_user': author_user,
                   'reviewer_user': reviewer_user, 'event': event, 'material': material,
                   'document': document, 'pdf': pdf}
        finally:
            reviewer.close()
            observer.close()


def content(case, **changes):
    event = case['event']
    body = signed(expected_revision=0, expected_fingerprint=None,
        title='Synthetic independent event expectation',
        event_ref={'event_id': event['id'], 'event_revision_id': event['revision_id'],
                   'event_fingerprint': event['fingerprint']},
        materials=[deepcopy(case['material'])], link_refs=[],
        expected={'event': deepcopy(EVENT),
                  'identity_assertions': [
                      {'participant_key': key, 'truth': 'unknown', 'sku_label': None,
                       'expected_variant_id': None} for key in ('a', 'b')],
                  'distinct_pairs': []},
        evidence_note='Independently transcribed from a synthetic original')
    body.update(changes)
    return body


def create_case(case, **changes):
    return ok(post(case['author'], '/cases', content(case, **changes)), 201)


def review_body(case, row, action='approve', **changes):
    material = case['material']
    body = signed(expected_revision=row.get('review_revision', 0),
        expected_fingerprint=row.get('review_fingerprint'),
        case_revision=row['revision'], case_fingerprint=row['fingerprint'],
        action=action, acknowledged=True,
        opened_materials=[{'document_id': material['document_id'],
                           'raw_hash': material['expected_raw_hash'],
                           'metadata_hash': material['expected_metadata_hash']}])
    body.update(changes)
    return body


def approve(case, row):
    return ok(post(case['reviewer'], f'/cases/{row["id"]}/reviews', review_body(case, row)), 201)


def set_body(row, **changes):
    body = signed(expected_revision=0, expected_fingerprint=None,
        title='Synthetic one-event frozen set', action='freeze', acknowledged=True,
        case_refs=[{'case_id': row['id'], 'case_revision': row['revision'],
                    'case_fingerprint': row['fingerprint'],
                    'review_revision': row['review_revision'],
                    'review_fingerprint': row['review_fingerprint']}])
    body.update(changes)
    return body


def frozen(case, row):
    return ok(post(case['reviewer'], '/sets', set_body(row)), 201)


def evaluate(case, set_row, target='frozen_revision'):
    return ok(post(case['author'], f'/sets/{set_row["id"]}/evaluate?mode=history', {
        'expected_set_revision': set_row['revision'],
        'expected_set_fingerprint': set_row['fingerprint'], 'target': target}))


def test_independent_expected_literal_persists_without_creating_facts(case):
    row = create_case(case)
    assert row['event_id'] == case['event']['id'] and row['expected']['event'] == EVENT
    assert row['event_snapshot'] == EVENT
    assert row['expected']['event']['measurements'][0]['raw_value'] == '38.00'
    assert row['expected']['event']['measurements'][1]['source_rank'] == 5
    assert row['review_status'] == 'pending'
    historical = ok(case['author'].get(f'{BASE}/cases/{row["id"]}?mode=history&revision=1'))
    assert historical['expected'] == row['expected'] and historical['is_current']
    listing = ok(case['author'].get(f'{BASE}/cases?mode=history&event_id={case["event"]["id"]}'))
    assert listing['total'] == 1 and 'expected' not in listing['items'][0]
    assert case['author'].get(f'{BASE}/cases/{row["id"]}').status_code == 422
    assert case['author'].get(f'{BASE}/cases/{row["id"]}?mode=history&revision=99').status_code == 404
    with case['database'].sessions() as db:
        for table in ('tire_variants', 'fact_versions', 'snapshots'):
            assert db.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one() == 0


@pytest.mark.parametrize('change', ['raw_as_float', 'negative_zero', 'rank_bool', 'missing_field',
                                    'foreign_participant', 'unknown_with_sku', 'duplicate_material',
                                    'zero_material', 'four_materials', 'missing_quote_right',
                                    'wrong_event_ref', 'cross_event_revision'])
def test_invalid_or_unbound_content_is_rejected_without_partial_case(case, change):
    body = content(case)
    if change == 'raw_as_float': body['expected']['event']['measurements'][0]['raw_value'] = 38.0
    elif change == 'negative_zero': body['expected']['event']['measurements'][0]['raw_value'] = '-0.00'
    elif change == 'rank_bool': body['expected']['event']['measurements'][0]['source_rank'] = True
    elif change == 'missing_field': del body['expected']['event']['measurements'][0]['source_rank']
    elif change == 'foreign_participant': body['expected']['identity_assertions'][0]['participant_key'] = 'foreign'
    elif change == 'unknown_with_sku': body['expected']['identity_assertions'][0]['sku_label'] = 'Guessed SKU'
    elif change == 'duplicate_material': body['materials'].append(deepcopy(body['materials'][0]))
    elif change == 'zero_material': body['materials'] = []
    elif change == 'four_materials': body['materials'] *= 4
    elif change == 'missing_quote_right': del body['materials'][0]['rights']['quote_test_results']
    elif change == 'wrong_event_ref': body['event_ref']['event_fingerprint'] = '0' * 64
    elif change == 'cross_event_revision':
        another = ok(case['author'].post('/v1/test-events', json=signed(event=deepcopy(EVENT))), 201)
        body['event_ref']['event_revision_id'] = another['revision_id']
    before = counts(case['database'])
    response = post(case['author'], '/cases', body)
    # -0.00 is a valid *literal* and must remain distinguishable from 0/0.00.
    if change == 'negative_zero':
        assert response.status_code == 201, response.text
        assert response.json()['expected']['event']['measurements'][0]['raw_value'] == '-0.00'
    else:
        assert response.status_code in {409, 422}, response.text
        assert counts(case['database']) == before


def test_case_and_set_uuid_replay_fence_and_admin_freeze(case):
    body = content(case)
    key = str(uuid4())
    first = ok(post(case['author'], '/cases', body, key=key), 201)
    again = ok(post(case['author'], '/cases', body, key=key), 201)
    assert (first['id'], first['revision'], first['fingerprint']) == (
        again['id'], again['revision'], again['fingerprint'])
    changed = deepcopy(body); changed['title'] = 'Changed request under reused UUID'
    assert post(case['author'], '/cases', changed, key=key).status_code == 409
    assert post(case['author'], f'/cases/{first["id"]}/revisions',
                changed).status_code in {409, 422}  # still carries create fence 0/null
    approved = approve(case, first)
    frozen_body = set_body(approved)
    assert post(case['observer'], '/sets', frozen_body).status_code == 403
    assert post(case['reviewer'], '/sets', set_body(approved, case_refs=[])).status_code == 422
    duplicate = [*frozen_body['case_refs'], *frozen_body['case_refs']]
    assert post(case['reviewer'], '/sets', set_body(approved, case_refs=duplicate)).status_code == 422
    set_key = str(uuid4())
    frozen_first = ok(post(case['reviewer'], '/sets', frozen_body, key=set_key), 201)
    frozen_again = ok(post(case['reviewer'], '/sets', frozen_body, key=set_key), 201)
    assert (frozen_first['id'], frozen_first['revision'], frozen_first['fingerprint']) == (
        frozen_again['id'], frozen_again['revision'], frozen_again['fingerprint'])
    changed_set = deepcopy(frozen_body); changed_set['title'] = 'Changed set on reused UUID'
    assert post(case['reviewer'], '/sets', changed_set, key=set_key).status_code == 409
    assert post(case['reviewer'], f'/sets/{frozen_first["id"]}/evaluate', {
        'expected_set_revision': 1, 'expected_set_fingerprint': frozen_first['fingerprint'],
        'target': 'frozen_revision'}).status_code == 422  # mode=history is mandatory


def test_freeze_checks_every_member_and_never_writes_a_partial_set(case):
    first = approve(case, create_case(case))
    second = approve(case, create_case(case, title='Another independent synthetic case'))
    stale_ref = set_body(second)['case_refs'][0]
    revised = content(case, expected_revision=second['revision'],
        expected_fingerprint=second['fingerprint'], title='Another case corrected')
    ok(post(case['author'], f'/cases/{second["id"]}/revisions', revised), 201)
    before = business_state(case['database'])
    request = set_body(first, case_refs=[*set_body(first)['case_refs'], stale_ref])
    assert post(case['reviewer'], '/sets', request).status_code in {409, 422}
    assert business_state(case['database']) == before


def test_content_review_and_set_revoke_never_resurrect_an_old_frozen_reference(case):
    first = approve(case, create_case(case))
    original_set = frozen(case, first)
    revised_body = content(case, expected_revision=first['revision'],
                           expected_fingerprint=first['fingerprint'],
                           title='Synthetic corrected expectation')
    revised = ok(post(case['author'], f'/cases/{first["id"]}/revisions', revised_body), 201)
    assert revised['revision'] == first['revision'] + 1
    historical = ok(case['author'].get(f'{BASE}/cases/{first["id"]}?mode=history&revision=1'))
    assert historical['fingerprint'] == first['fingerprint']
    assert historical['title'] == first['title']
    after_content = evaluate(case, original_set)
    assert after_content['state'] != 'passed' and not after_content['case_results'][0]['eligible']
    reapproved = approve(case, revised)
    assert evaluate(case, original_set)['case_results'][0]['eligible'] is False
    revoked_review = ok(post(case['reviewer'], f'/cases/{first["id"]}/reviews',
        review_body(case, reapproved, action='revoke')), 201)
    assert revoked_review['review_status'] == 'revoked'
    assert evaluate(case, original_set)['case_results'][0]['eligible'] is False
    # A later approval cannot rebind the old set's pinned content/review pair.
    reapproved_again = approve(case, revoked_review)
    assert reapproved_again['review_revision'] > first['review_revision']
    assert evaluate(case, original_set)['case_results'][0]['eligible'] is False
    set_revoke = set_body(reapproved_again, expected_revision=original_set['revision'],
        expected_fingerprint=original_set['fingerprint'], action='revoke', case_refs=[])
    revoked_set = ok(post(case['reviewer'], f'/sets/{original_set["id"]}/revisions', set_revoke), 201)
    assert revoked_set['state'] == 'revoked' and not revoked_set['eligible']
    old_set = ok(case['author'].get(f'{BASE}/sets/{original_set["id"]}?mode=history&revision=1'))
    assert old_set['case_refs'] == original_set['case_refs']
    assert old_set['fingerprint'] == original_set['fingerprint']


@pytest.mark.parametrize('damage', ['missing_original', 'same_length_bytes', 'metadata_drift'])
def test_missing_or_corrupt_original_marks_history_blocked_and_rejects_evaluate(case, damage):
    approved = approve(case, create_case(case))
    set_row = frozen(case, approved)
    if damage == 'metadata_drift':
        with case['database'].engine.begin() as connection:
            connection.execute(text('UPDATE evidence_documents SET title=:title WHERE id=:id'),
                               {'title': 'Tampered synthetic metadata', 'id': case['document']['id']})
    else:
        with case['database'].sessions() as db:
            path = db.info['object_store'].path(case['document']['raw_hash'])
        if damage == 'missing_original':
            path.unlink()
        else:
            source = case['pdf']
            changed = source[:25] + bytes([source[25] ^ 1]) + source[26:]
            assert len(changed) == len(source)
            path.write_bytes(changed)
    after_damage = business_state(case['database'])
    history = ok(case['author'].get(f'{BASE}/cases/{approved["id"]}?mode=history'))
    assert history['expected'] == approved['expected'] and history['blockers']
    assert any('material' in item for item in history['blockers'])
    assert history['review_status'] == 'approved'  # Recorded review, not current eligibility.
    response = post(case['author'], f'/sets/{set_row["id"]}/evaluate?mode=history', {
        'expected_set_revision': set_row['revision'],
        'expected_set_fingerprint': set_row['fingerprint'],
        'target': 'frozen_revision'})
    assert response.status_code in {409, 422}, response.text
    assert business_state(case['database']) == after_damage


def test_pure_difference_and_distinct_pair_oracles_keep_unknown_and_type_boundaries():
    differences, truncated = compare_values(
        {'raw_value': '-0.00', 'source_rank': 0, 'nullable': None},
        {'raw_value': '0.00', 'source_rank': False})
    assert not truncated
    assert {row['path'] for row in differences} == {
        'event.raw_value', 'event.source_rank', 'event.nullable'}
    assert next(row for row in differences if row['path'] == 'event.source_rank') == {
        'path': 'event.source_rank', 'expected': 0, 'actual': False, 'code': 'value_mismatch'}
    expected = {'identity_assertions': [
        {'participant_key': 'a', 'truth': 'linked', 'sku_label': 'Known A', 'expected_variant_id': 'v-a'},
        {'participant_key': 'b', 'truth': 'linked', 'sku_label': 'Known B', 'expected_variant_id': 'v-b'}],
        'distinct_pairs': [{'left_sku_label': 'Known A', 'right_sku_label': 'Known B'}]}
    same_variant = {'a': {'linked': True, 'variant_id': 'shared', 'identity_key': 'identity-a', 'blockers': []},
                    'b': {'linked': True, 'variant_id': 'shared', 'identity_key': 'identity-b', 'blockers': []}}
    _identities, distinct, wrong, checked = compare_identities(expected, same_variant)
    assert (wrong, checked) == (1, 1) and distinct[0]['state'] == 'failed'
    same_identity = deepcopy(same_variant)
    same_identity['b'].update(variant_id='other', identity_key='identity-a')
    assert compare_identities(expected, same_identity)[2:] == (1, 1)
    ineligible_collision = deepcopy(same_variant)
    ineligible_collision['b']['linked'] = False
    _identities, distinct, wrong, checked = compare_identities(expected, ineligible_collision)
    assert (wrong, checked) == (1, 0) and distinct[0]['state'] == 'failed'
    ineligible_distinct = deepcopy(ineligible_collision)
    ineligible_distinct['b'].update(variant_id='other', identity_key='identity-b')
    _identities, distinct, wrong, checked = compare_identities(expected, ineligible_distinct)
    assert (wrong, checked) == (0, 0) and distinct[0]['state'] == 'inconclusive'
    negative = {'identity_assertions': [
        {'participant_key': 'a', 'truth': 'not_linked', 'sku_label': 'Known negative',
         'expected_variant_id': 'expected-target'}], 'distinct_pairs': []}
    observed_wrong_target = {'a': {'linked': False, 'variant_id': 'other-target',
                                   'identity_key': 'identity-a', 'blockers': []}}
    identities, _distinct, wrong, checked = compare_identities(negative, observed_wrong_target)
    assert identities[0]['state'] == 'failed' and (wrong, checked) == (0, 0)
    unknown = {'identity_assertions': [
        {'participant_key': 'a', 'truth': 'unknown', 'sku_label': None, 'expected_variant_id': None}],
        'distinct_pairs': []}
    assert compare_identities(unknown, {})[2:] == (0, 0)


def test_real_reviewed_bridge_revision_aba_invalidates_old_case_and_set(bridge_case):
    bridge = reviewed_bridge(bridge_case)
    assert bridge['eligibility'] == 'conditional_reviewed_transcription'
    event = deepcopy(EVENT)
    event.update(title='R71 合成验收 · 测试对象与精确 SKU',
                 organization='Project-authored synthetic QA', tested_size='245/40R20',
                 source_url='https://fixture.invalid/test',
                 rights_basis='Project-authored synthetic fixture for local verification only.')
    event['participants'][0].update(brand='Synthetic', model='Synthetic Tire',
        source_designation='Synthetic participant a; see material page 1')
    material = deepcopy(bridge_case.proposal['materials'][0])
    material['rights']['quote_test_results'] = True
    adapter = {'author': bridge_case.creator, 'reviewer': bridge_case.reviewer,
               'event': bridge_case.event, 'material': material}
    body = content(adapter)
    body['expected']['event'] = event
    body['link_refs'] = [{'participant_key': 'a', 'link_id': bridge['id'],
        'link_revision_id': bridge['revision_id'], 'link_fingerprint': bridge['fingerprint']}]
    body['expected']['identity_assertions'][0] = {
        'participant_key': 'a', 'truth': 'linked', 'sku_label': 'Known synthetic A',
        'expected_variant_id': bridge_case.selection['variant_id']}
    golden = ok(post(bridge_case.creator, '/cases', body), 201)
    golden = ok(post(bridge_case.reviewer, f'/cases/{golden["id"]}/reviews',
        review_body(adapter, golden)), 201)
    set_row = frozen(adapter, golden)
    baseline = evaluate(adapter, set_row)
    assert baseline['case_results'][0]['identity_results'][0]['checked'] is True
    before = business_state(bridge_case.database)
    assert evaluate(adapter, set_row) == baseline
    assert business_state(bridge_case.database) == before
    revoked = bridge_link_view(submit_bridge(bridge_case,
        bridge_decision(bridge_case, bridge_case.reviewer, action='revoke', link=bridge),
        bridge_case.reviewer))
    after_revoke = evaluate(adapter, set_row, 'current_head')
    assert not after_revoke['case_results'][0]['eligible']
    restored = bridge_link_view(submit_bridge(bridge_case,
        bridge_decision(bridge_case, bridge_case.reviewer, action='restore', link=revoked),
        bridge_case.reviewer))
    rereviewed = bridge_link_view(submit_bridge(bridge_case,
        bridge_decision(bridge_case, bridge_case.reviewer, action='review', link=restored),
        bridge_case.reviewer))
    assert rereviewed['selection'] == bridge['selection']
    assert rereviewed['fingerprint'] != bridge['fingerprint']
    after_aba = evaluate(adapter, set_row, 'current_head')
    assert not after_aba['case_results'][0]['eligible']


def test_review_requires_distinct_admin_account_complete_opened_materials_and_uuid_replay(case):
    row = create_case(case)
    body = review_body(case, row)
    before = counts(case['database'])
    assert post(case['observer'], f'/cases/{row["id"]}/reviews', body).status_code == 403
    assert post(case['author'], f'/cases/{row["id"]}/reviews', body).status_code in {403, 409, 422}
    alias = TestClient(case['app'])
    try:
        ok(alias.post('/v1/auth/login', json={'username': 'r119-author', 'password': PASSWORD}))
        assert alias.cookies['tire_local_session'] != case['author'].cookies['tire_local_session']
        assert post(alias, f'/cases/{row["id"]}/reviews', body).status_code in {403, 409, 422}
    finally:
        alias.close()
    assert post(case['reviewer'], f'/cases/{row["id"]}/reviews',
                review_body(case, row, opened_materials=[])).status_code in {409, 422}
    assert counts(case['database']) == before
    key = str(uuid4())
    first = ok(post(case['reviewer'], f'/cases/{row["id"]}/reviews', body, key=key), 201)
    again = ok(post(case['reviewer'], f'/cases/{row["id"]}/reviews', body, key=key), 201)
    assert first['review_revision'] == again['review_revision'] == 1
    assert first['review_fingerprint'] == again['review_fingerprint']
    reviewer_alias = TestClient(case['app'])
    try:
        ok(reviewer_alias.post('/v1/auth/login', json={
            'username': 'r119-reviewer', 'password': PASSWORD}))
        assert reviewer_alias.cookies['tire_local_session'] != case['reviewer'].cookies['tire_local_session']
        replay = ok(post(reviewer_alias, f'/cases/{row["id"]}/reviews', body, key=key), 201)
        assert replay['review_revision'] == first['review_revision']
        assert replay['review_fingerprint'] == first['review_fingerprint']
    finally:
        reviewer_alias.close()
    changed = deepcopy(body); changed['reason'] = 'Different signed statement on same UUID'
    assert post(case['reviewer'], f'/cases/{row["id"]}/reviews', changed, key=key).status_code == 409
    assert first['review_status'] == 'approved'


def test_frozen_and_current_evaluations_preserve_raw_decimal_rank_and_read_only_state(case):
    row = approve(case, create_case(case))
    frozen_set = frozen(case, row)
    before = business_state(case['database'])
    baseline = evaluate(case, frozen_set)
    assert baseline['schema'] == 'test-event-golden-evaluation@1'
    assert baseline['wrong_merge_count'] is None
    assert baseline['human_truth_status'] == 'pending_external_review'
    assert baseline['case_results'][0]['differences'] == []
    assert baseline['case_results'][0]['comparison']['ranking'] == 'source_reported_only'
    assert business_state(case['database']) == before
    revised_event = deepcopy(EVENT)
    revised_event['measurements'][0]['raw_value'] = '38.0'
    revised_event['measurements'][1]['source_rank'] = 4
    revised_event['conditions'] = 'Synthetic 80 to 20 km/h wet braking; dry temperature omitted'
    revised_event['metrics'][0]['unit'] = 'ft'
    event_id = case['event']['id']
    ok(case['author'].put(f'/v1/test-events/{event_id}', json=signed(
        event=revised_event, expected_revision=1)))
    before = business_state(case['database'])
    current = evaluate(case, frozen_set, 'current_head')
    assert current['state'] != 'passed'
    result = current['case_results'][0]
    assert result['eligible'] is False and result['actual_event_revision_id'] != result['expected_event_revision_id']
    assert any(item['expected'] == '38.00' and item['actual'] == '38.0' for item in result['differences'])
    assert any(item['expected'] == 5 and item['actual'] == 4 for item in result['differences'])
    assert any(item['expected'] == 'm' and item['actual'] == 'ft' for item in result['differences'])
    assert business_state(case['database']) == before
    old = evaluate(case, frozen_set)
    assert old['case_results'][0]['differences'] == []
    assert business_state(case['database']) == before
