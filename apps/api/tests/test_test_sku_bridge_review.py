"""Independent R71 adversarial contract review; synthetic material is never real evidence.

Only public HTTP behavior determines eligibility. SQL is used solely to arrange
private corruption/immutability probes and to count side effects.
"""
from copy import deepcopy
from datetime import timedelta
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from tire_api.db import EvidenceDocument, EvidenceObject, FactVersion, Snapshot, utcnow
from tire_api.documents import document_metadata
from tire_api.domain import VariantInput, digest
from tire_api.main import create_app
from test_core import FixtureRegistry, success
from test_fitment_relations import tire_payload
from test_test_events import PAYLOAD


BASE = '/v1/test-sku-links'
EXPLICIT = 'source_explicit_identifiers_in_supplied_material'
PASSWORD = secrets.token_urlsafe(24)
PRIVATE_ROOT = Path(os.environ['R71_REVIEW_STORAGE_ROOT'])


def passed(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def link_view(response, status=201):
    payload = passed(response, status)
    return payload.get('link', payload)


def synthetic_pdf(lines):
    """One actual PDF page, deliberately marked synthetic; no external renderer."""
    content = 'BT /F1 8 Tf 30 800 Td ' + ' '.join(
        '(' + line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ') Tj 0 -15 Td'
        for line in lines) + ' ET'
    stream = content.encode('ascii')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    data = bytearray(b'%PDF-1.4\n% SYNTHETIC CONTRACT FIXTURE - NOT A REAL TEST REPORT\n')
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{index} 0 obj\n'.encode() + value + b'\nendobj\n')
    xref = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(data)


def table_counts(database):
    with database.engine.connect() as connection:
        return {name: connection.execute(text('SELECT COUNT(*) FROM "' + name + '"')).scalar_one()
                for name in inspect(connection).get_table_names() if 'session' not in name.lower()}


def register(client, username):
    return passed(client.post('/v1/auth/register', json={'username': username, 'password': PASSWORD}))['user']


def login(client, username):
    return passed(client.post('/v1/auth/login', json={'username': username, 'password': PASSWORD}))


def adopt(case, rows, marker):
    case.registry.result = success(marker, rows)
    result = passed(case.creator.post('/v1/sources/fixture/live-query', json={
        'query': {'size': case.tire['size']}, 'fallback_policy': 'never'}))
    assert result['data_state'] == 'live', result
    return result


def document_binding(case, document_id):
    with case.database.sessions() as db:
        row = db.get(EvidenceDocument, document_id)
        obj = db.get(EvidenceObject, row.raw_hash)
        metadata = {**document_metadata(row, obj.byte_count), 'actor_session_id': row.actor_session_id}
        return {'document_id': row.id, 'expected_raw_hash': row.raw_hash,
                'expected_metadata_hash': digest(metadata)}


def upload(case, pdf=None, **changes):
    metadata = {'title': 'Project-authored synthetic test identifiers',
        'source_url': case.event_payload['event']['source_url'],
        'operator': 'Synthetic supplied-material author',
        'rights_basis': 'Project-authored synthetic material; local workspace contract testing only', **changes}
    response = case.creator.post('/v1/documents', content=pdf or case.pdf,
        headers={'Content-Type': 'application/pdf', 'X-Evidence-Metadata':
                 base64.b64encode(json.dumps(metadata).encode()).decode()})
    return passed(response, 201)


@pytest.fixture
def case():
    storage = PRIVATE_ROOT / uuid4().hex[:8]
    storage.mkdir(exist_ok=False)
    os.environ['TI_OBJECT_STORE_ROOT'] = str(storage / 'objects')
    os.environ['TI_PARSER_BUNDLE_ROOT'] = str(storage / 'bundles')
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (storage / 'private.sqlite').as_posix(), registry)
    with TestClient(app) as creator:
        creator_user = register(creator, 'r71-declarer')
        reviewer, observer = TestClient(app), TestClient(app)
        try:
            reviewer_user = register(reviewer, 'r71-reviewer')
            observer_user = register(observer, 'r71-observer')
            passed(creator.post('/v1/auth/users/' + reviewer_user['id'] + '/role', json={'is_admin': True}))
            value = SimpleNamespace(app=app, database=app.state.database, registry=registry,
                creator=creator, reviewer=reviewer, observer=observer,
                creator_user=creator_user, reviewer_user=reviewer_user, observer_user=observer_user,
                tire=tire_payload(), storage=storage)
            accepted = adopt(value, [value.tire], 'Synthetic R71 accepted source bytes')
            variant = accepted['variants'][0]
            snapshot_id = accepted['provenance'][0]['snapshot_id']
            with value.database.sessions() as db:
                fact_id = db.scalar(select(FactVersion.id).where(
                    FactVersion.variant_id == variant['id'], FactVersion.snapshot_id == snapshot_id))
            event_payload = deepcopy(PAYLOAD)
            event_payload['event']['tested_size'] = value.tire['size']
            event_payload['event']['participants'][0].update(brand=value.tire['brand'], model=value.tire['model'])
            value.event_payload = event_payload
            value.event = passed(creator.post('/v1/test-events', json=event_payload), 201)
            value.selection = {'event_id': value.event['id'], 'event_revision_id': value.event['revision_id'],
                'participant_key': 'a', 'variant_id': variant['id'], 'tire_snapshot_id': snapshot_id,
                'fact_version_id': fact_id}
            value.identity = VariantInput.model_validate(value.tire).identity()
            lines = ['SYNTHETIC MATERIAL - NO REAL PUBLISHER OR TEST', 'Synthetic same-event comparison',
                'Participant a: Synthetic Synthetic Tire'] + [f'{k} = {v}' for k, v in value.identity.items()]
            value.pdf = synthetic_pdf(lines)
            value.document = upload(value)
            material = {**document_binding(value, value.document['id']),
                'event_locator': {'page': 1, 'region': 'synthetic page title', 'quote': lines[1]},
                'participant_locator': {'page': 1, 'region': 'synthetic participant row', 'quote': lines[2]},
                'rights': {'rights_holder': 'Project synthetic fixture authors',
                    'basis': 'Project-owned synthetic fixture only', 'store_original': True,
                    'workspace_reopen': True, 'quote_identifiers': True}}
            value.proposal = {'mode': 'history', 'action': 'create', 'link_id': None,
                'selection': deepcopy(value.selection), 'materials': [material],
                'assertions': [{'field': key, 'material_document_id': value.document['id'],
                    'material_value': val, 'quote': f'{key} = {val}', 'page': 1,
                    'region': 'synthetic identity row ' + key} for key, val in value.identity.items()],
                'evidence_level': EXPLICIT}
            yield value
        finally:
            reviewer.close()
            observer.close()


def preview(case, client=None, proposal=None, *, action=None, link=None):
    payload = deepcopy(proposal or case.proposal)
    if action is not None:
        payload.update(action=action, link_id=link['id'])
    response = (client or case.creator).post(BASE + '/preview', json=payload)
    return response


def decision(case, client=None, proposal=None, *, action=None, link=None):
    payload = deepcopy(proposal or case.proposal)
    if action is not None:
        payload.update(action=action, link_id=link['id'])
    view = passed(preview(case, client, payload))
    return {**payload, 'expected_revision': view['revision'], 'expected_fingerprint': view['fingerprint'],
        'declaration_revision_id': view.get('declaration_revision_id'),
        'operator': 'Synthetic R71 contract reviewer', 'reason': 'Synthetic private adversarial review only',
        'acknowledged': True,
        'opened_materials': [{'document_id': row['document_id'], 'raw_hash': row['expected_raw_hash'],
                              'metadata_hash': row['expected_metadata_hash']} for row in payload['materials']],
        'confirmed_event_revision_id': payload['selection']['event_revision_id'],
        'confirmed_participant_hash': view['frozen_evidence']['test']['participant_hash']}


def submit(case, payload, client=None, key=None):
    return (client or case.creator).post(BASE + '/decisions', json=payload,
        headers={'Idempotency-Key': key or str(uuid4())})


def create(case, proposal=None):
    return link_view(submit(case, decision(case, proposal=proposal)))


def reviewed(case, proposal=None):
    link = create(case, proposal)
    request = decision(case, case.reviewer, proposal, action='review', link=link)
    return link_view(submit(case, request, case.reviewer))


def read(case, link, *, revision=None, client=None):
    return (client or case.creator).get(BASE + '/' + link['id'],
        params={'mode': 'history', **({'revision': revision} if revision is not None else {})})


def assert_limited(view):
    assert view['eligibility'] in {'none', 'conditional_reviewed_transcription'}
    serialized = json.dumps(view['boundary'], sort_keys=True)
    assert 'operator_supplied' in serialized and 'unverified' in serialized and 'local_workspace' in serialized
    assert 'online_verified' not in serialized and 'independent_verified' not in serialized


def assert_rejected(response):
    assert response.status_code in {403, 404, 409, 422, 503}, response.text


def test_positive_two_account_review_preserves_complete_original_material_and_source_axes(case):
    before = table_counts(case.database)
    proposed = passed(preview(case))
    assert proposed['can_submit'], proposed['blockers']
    assert table_counts(case.database) == before
    link = reviewed(case)
    assert link['review_state'] == 'reviewed'
    assert link['eligibility'] == 'conditional_reviewed_transcription'
    assert link['declared_by_user_id'] == case.creator_user['id']
    assert_limited(link)
    assert link['frozen_evidence']['test']['participant'] == case.event['event']['participants'][0]
    assert link['frozen_evidence']['test']['participant_hash'] == digest(case.event['event']['participants'][0])
    assert link['frozen_evidence']['tire']['fact_version_id'] == case.selection['fact_version_id']
    before = table_counts(case.database)
    historical = passed(read(case, link, revision=1))
    assert historical['review_state'] == 'pending_review'
    assert historical['declared_by_user_id'] == case.creator_user['id']
    assert table_counts(case.database) == before
    assert read(case, link, revision=999999).status_code == 404
    assert 'source_explicit_identifiers_in_supplied_material' in json.dumps(link)


def test_same_account_different_session_cannot_self_review(case):
    link = create(case)
    alias = TestClient(case.app)
    try:
        login(alias, 'r71-declarer')
        assert alias.cookies['tire_local_session'] != case.creator.cookies['tire_local_session']
        request = decision(case, alias, action='review', link=link)
        request['operator'] = 'A completely different claimed human name'
        before = table_counts(case.database)
        assert_rejected(submit(case, request, alias))
        assert table_counts(case.database) == before
    finally:
        alias.close()


def test_review_cannot_replace_material_assertion_or_selection_in_the_same_operation(case):
    link = create(case)
    request = decision(case, case.reviewer, action='review', link=link)
    for field in ('quote', 'region', 'material_value'):
        tampered = deepcopy(request)
        tampered['assertions'][0][field] = 'REPLACED DECLARATION'
        assert_rejected(submit(case, tampered, case.reviewer))
    tampered = deepcopy(request)
    tampered['materials'][0]['event_locator']['quote'] = 'Another event claimed by reviewer'
    assert_rejected(submit(case, tampered, case.reviewer))
    assert passed(read(case, link))['revision'] == 1


def test_revoke_restore_preserves_declarer_and_requires_fresh_review(case):
    link = reviewed(case)
    declaration_id = link['declaration_revision_id']
    revoked = link_view(submit(case, decision(case, case.reviewer, action='revoke', link=link), case.reviewer))
    assert revoked['review_state'] == 'revoked' and revoked['eligibility'] == 'none'
    assert_rejected(submit(case, decision(case, case.reviewer, action='review', link=revoked), case.reviewer))
    restored = link_view(submit(case, decision(case, case.reviewer, action='restore', link=revoked), case.reviewer))
    assert restored['review_state'] == 'pending_review' and restored['eligibility'] == 'none'
    assert restored['declared_by_user_id'] == case.creator_user['id']
    assert restored['declaration_revision_id'] == declaration_id
    rereview = link_view(submit(case, decision(case, case.reviewer, action='review', link=restored), case.reviewer))
    assert rereview['eligibility'] == 'conditional_reviewed_transcription'


def test_revise_transfers_declaration_to_actual_account_not_operator_text(case):
    link = reviewed(case)
    changed = deepcopy(case.proposal)
    changed['assertions'][0]['region'] = 'New synthetic source position'
    request = decision(case, case.reviewer, changed, action='revise', link=link)
    request['operator'] = 'r71-declarer'
    revised = link_view(submit(case, request, case.reviewer))
    assert revised['review_state'] == 'pending_review'
    assert revised['declared_by_user_id'] == case.reviewer_user['id']
    assert revised['declaration_revision_id'] != link['declaration_revision_id']
    self_request = decision(case, case.reviewer, changed, action='review', link=revised)
    assert_rejected(submit(case, self_request, case.reviewer))
    accepted = link_view(submit(case, decision(case, case.creator, changed, action='review', link=revised)))
    assert accepted['eligibility'] == 'conditional_reviewed_transcription'


@pytest.mark.parametrize('field,value', [
    ('actor_user_id', 'forged'), ('origin_verification', 'online_verified'),
    ('eligibility', 'conditional_reviewed_transcription'), ('event_payload', {}),
    ('material_origin', 'publisher_authenticated'), ('facts', {'wet_braking': 1}),
])
def test_client_cannot_supply_authority_actor_or_facts(case, field, value):
    request = deepcopy(case.proposal)
    request[field] = value
    assert preview(case, proposal=request).status_code == 422


@pytest.mark.parametrize('level', ['source_explicit_identifiers', 'online_verified', 'independent_verified'])
def test_bare_source_authentication_levels_are_not_accepted(case, level):
    request = deepcopy(case.proposal)
    request['evidence_level'] = level
    assert preview(case, proposal=request).status_code == 422


@pytest.mark.parametrize('field', ['materials', 'assertions'])
def test_explicit_level_without_direct_material_or_identifiers_cannot_be_eligible(case, field):
    request = deepcopy(case.proposal)
    request[field] = []
    response = preview(case, proposal=request)
    if response.status_code == 200:
        view = response.json()
        assert not view['can_submit'] or view['eligibility'] == 'none'
        if view['can_submit']:
            link = reviewed(case, request)
            assert link['eligibility'] == 'none'
    else:
        assert_rejected(response)


def test_manual_assertion_can_be_reviewed_as_a_clue_but_not_promoted(case):
    request = {**deepcopy(case.proposal), 'materials': [], 'assertions': [], 'evidence_level': 'manual_assertion'}
    link = reviewed(case, request)
    assert link['review_state'] == 'reviewed' and link['eligibility'] == 'none'
    assert_limited(link)


@pytest.mark.parametrize('field,value', [('run_flat', True), ('product_code_type', 'EAN'),
    ('manufacturer_product_code', 'SYNTHETIC-OTHER'), ('region', 'US'), ('size', '245/40ZR20')])
def test_identifier_disagreement_cannot_be_overridden_by_manual_review(case, field, value):
    request = deepcopy(case.proposal)
    next(row for row in request['assertions'] if row['field'] == field)['material_value'] = value
    response = preview(case, proposal=request)
    if response.status_code == 200:
        assert response.json()['eligibility'] == 'none'
        if response.json()['can_submit']:
            assert reviewed(case, request)['eligibility'] == 'none'
    else:
        assert_rejected(response)


@pytest.mark.parametrize('field', ['product_code_type', 'run_flat', 'region', 'manufacturer_product_code'])
def test_missing_declared_identity_is_not_filled_from_the_sku_catalog(case, field):
    request = deepcopy(case.proposal)
    request['assertions'] = [row for row in request['assertions'] if row['field'] != field]
    view = passed(preview(case, proposal=request))
    assert view['eligibility'] == 'none'
    if view['can_submit']:
        assert reviewed(case, request)['eligibility'] == 'none'


@pytest.mark.parametrize('location,value', [('page', True), ('page', 0), ('page', 100001),
    ('material_value', 0), ('material_value', None), ('material_value', []), ('quote', ''), ('region', '')])
def test_assertion_strict_types_and_bounded_manual_locators(case, location, value):
    request = deepcopy(case.proposal)
    request['assertions'][0][location] = value
    assert preview(case, proposal=request).status_code == 422


@pytest.mark.parametrize('mutation', ['duplicate_field', 'unknown_field', 'wrong_document', 'duplicate_material',
    'event_page_bool', 'participant_quote_empty', 'rights_false', 'rights_integer', 'provider_permission'])
def test_material_scope_and_rights_are_not_free_form_authority(case, mutation):
    request = deepcopy(case.proposal)
    if mutation == 'duplicate_field':
        request['assertions'].append(deepcopy(request['assertions'][0]))
    elif mutation == 'unknown_field':
        request['assertions'][0]['field'] = 'performance_winner'
    elif mutation == 'wrong_document':
        request['assertions'][0]['material_document_id'] = str(uuid4())
    elif mutation == 'duplicate_material':
        request['materials'].append(deepcopy(request['materials'][0]))
    elif mutation == 'event_page_bool':
        request['materials'][0]['event_locator']['page'] = True
    elif mutation == 'participant_quote_empty':
        request['materials'][0]['participant_locator']['quote'] = ''
    elif mutation in {'rights_false', 'rights_integer'}:
        request['materials'][0]['rights']['store_original'] = False if mutation == 'rights_false' else 1
    else:
        request['materials'][0]['rights']['provider_use'] = True
    response = preview(case, proposal=request)
    if response.status_code == 200:
        assert not response.json()['can_submit']
    else:
        assert_rejected(response)


@pytest.mark.parametrize('field', ['assertion_quote', 'assertion_region', 'event_quote', 'event_region',
    'participant_quote', 'participant_region', 'rights_holder', 'rights_basis', 'operator', 'reason'])
def test_all_human_attestations_reject_whitespace_only_without_silent_trimming(case, field):
    request = deepcopy(case.proposal)
    if field.startswith('assertion_'):
        request['assertions'][0][field.removeprefix('assertion_')] = ' \t\n '
    elif field.startswith(('event_', 'participant_')):
        prefix, key = field.split('_', 1)
        request['materials'][0][prefix + '_locator'][key] = ' \t\n '
    elif field == 'rights_holder':
        request['materials'][0]['rights']['rights_holder'] = ' \t\n '
    elif field == 'rights_basis':
        request['materials'][0]['rights']['basis'] = ' \t\n '
    else:
        payload = decision(case)
        payload[field] = ' \t\n ' * 2
        assert submit(case, payload).status_code == 422
        return
    assert preview(case, proposal=request).status_code == 422


@pytest.mark.parametrize('field,value', [('acoustic_technology', None),
    ('facts', {'product_code_type': 'MSPN', 'technology_features': ['Synthetic acoustic'], 'utqg_treadwear': 300})])
def test_unknown_or_array_identity_cannot_be_filled_or_flattened_into_exact_eligibility(case, field, value):
    changed = deepcopy(case.tire)
    changed[field] = value
    result = adopt(case, [changed], 'Synthetic incomplete or array identity')
    variant_id, snapshot_id = result['variants'][0]['id'], result['provenance'][0]['snapshot_id']
    with case.database.sessions() as db:
        fact_id = db.scalar(select(FactVersion.id).where(
            FactVersion.variant_id == variant_id, FactVersion.snapshot_id == snapshot_id))
    request = deepcopy(case.proposal)
    request['selection'].update(variant_id=variant_id, tire_snapshot_id=snapshot_id, fact_version_id=fact_id)
    if field == 'facts':
        request['assertions'].append({'field': 'technology_features', 'material_document_id': case.document['id'],
            'material_value': '["Synthetic acoustic"]', 'quote': 'Synthetic acoustic', 'page': 1,
            'region': 'Synthetic array identity statement'})
    response = preview(case, proposal=request)
    if response.status_code == 200:
        assert response.json()['eligibility'] == 'none'
        assert response.json()['unknown_fields'] or response.json()['blockers']
        if response.json()['can_submit']:
            assert reviewed(case, request)['eligibility'] == 'none'
    else:
        assert_rejected(response)


@pytest.mark.parametrize('attack', ['missing', 'duplicate', 'wrong_raw', 'wrong_meta', 'wrong_event', 'wrong_participant'])
def test_review_requires_exact_material_and_original_participant_confirmation(case, attack):
    link = create(case)
    request = decision(case, case.reviewer, action='review', link=link)
    if attack == 'missing':
        request['opened_materials'] = []
    elif attack == 'duplicate':
        request['opened_materials'].append(deepcopy(request['opened_materials'][0]))
    elif attack in {'wrong_raw', 'wrong_meta'}:
        request['opened_materials'][0]['raw_hash' if attack == 'wrong_raw' else 'metadata_hash'] = '0' * 64
    elif attack == 'wrong_event':
        request['confirmed_event_revision_id'] = str(uuid4())
    else:
        request['confirmed_participant_hash'] = '0' * 64
    assert_rejected(submit(case, request, case.reviewer))
    assert passed(read(case, link))['review_state'] == 'pending_review'


def test_supplied_pdf_publisher_claim_and_signature_text_do_not_authenticate_source(case):
    document = upload(case, title='ADAC official publisher-authenticated report',
        operator='Independent publisher certification', rights_basis='Claimed publisher license')
    request = deepcopy(case.proposal)
    request['materials'][0].update(document_binding(case, document['id']))
    for row in request['assertions']:
        row['material_document_id'] = document['id']
    link = reviewed(case, request)
    assert_limited(link)
    assert link['eligibility'] == 'conditional_reviewed_transcription'
    event = passed(case.creator.get('/v1/test-events/' + case.event['id'], params={'mode': 'history'}))
    assert event['verification_status'] == 'unverified' and event['record_kind'] == 'manual_transcription'


def test_preview_listing_and_exact_history_have_no_business_or_audit_writes(case):
    link = reviewed(case)
    before = table_counts(case.database)
    for response in [preview(case), case.creator.get(BASE + '/materials', params={'mode': 'history'}),
        case.creator.get(BASE, params={'mode': 'history', 'event_id': case.event['id']}),
        read(case, link), read(case, link, revision=1)]:
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
    assert table_counts(case.database) == before


def test_every_bridge_preview_and_write_requires_current_admin(case):
    for client in [case.observer, TestClient(case.app)]:
        try:
            assert preview(case, client).status_code == 403
            request = decision(case)
            assert submit(case, request, client).status_code == 403
        finally:
            if client is not case.observer:
                client.close()
    link = create(case)
    assert case.observer.get(BASE + '/' + link['id']).status_code == 422
    assert passed(read(case, link, client=case.observer))['id'] == link['id']


def test_metadata_digest_includes_original_actor_even_when_every_public_field_is_unchanged(case):
    with case.database.engine.begin() as connection:
        connection.execute(text('UPDATE evidence_documents SET actor_session_id=:value WHERE id=:id'),
            {'value': case.reviewer.cookies['tire_local_session'], 'id': case.document['id']})
    assert_rejected(preview(case))


@pytest.mark.parametrize('field', ['title', 'rights_basis', 'operator', 'source_url'])
def test_material_metadata_mutation_invalidates_old_preview_and_frozen_evidence(case, field):
    link = reviewed(case)
    value = 'https://fixture.invalid/replaced.pdf' if field == 'source_url' else 'CORRUPTED MATERIAL METADATA'
    with case.database.engine.begin() as connection:
        connection.execute(text('UPDATE evidence_documents SET ' + field + '=:value WHERE id=:id'),
            {'value': value, 'id': case.document['id']})
    assert_rejected(preview(case))
    response = read(case, link)
    assert_rejected(response)
    assert 'CORRUPTED MATERIAL METADATA' not in response.text


@pytest.mark.parametrize('attack', ['bytes', 'size', 'mapping'])
def test_missing_or_corrupt_authoritative_object_never_falls_back(case, attack):
    link = reviewed(case)
    with case.database.sessions() as db:
        store = db.info['object_store']
    if attack == 'bytes':
        store.path(case.document['raw_hash']).write_bytes(b'CORRUPTED ORIGINAL PDF')
    elif attack == 'size':
        with case.database.engine.begin() as connection:
            connection.execute(text('UPDATE evidence_objects SET byte_count=byte_count+1 WHERE raw_hash=:hash'),
                {'hash': case.document['raw_hash']})
    else:
        from tire_api.documents import record_object
        with case.database.sessions() as db:
            changed_hash = record_object(db, case.pdf + b'\nDIFFERENT SUPPLIED MATERIAL\n')
            db.commit()
        with case.database.engine.begin() as connection:
            connection.execute(text('UPDATE evidence_documents SET raw_hash=:hash WHERE id=:id'),
                {'hash': changed_hash, 'id': case.document['id']})
    for response in [preview(case), read(case, link), read(case, link, revision=1)]:
        assert_rejected(response)
        assert 'CORRUPTED ORIGINAL PDF' not in response.text


def test_idempotency_stable_user_scope_survives_new_session_and_never_reexecutes_old_write(case):
    request, key = decision(case), str(uuid4())
    first = submit(case, request, key=key)
    link = link_view(first)
    reviewed_link = link_view(submit(case, decision(case, case.reviewer, action='review', link=link), case.reviewer))
    alias = TestClient(case.app)
    try:
        login(alias, 'r71-declarer')
        before = table_counts(case.database)
        replay = submit(case, request, alias, key=key)
        assert replay.status_code in {200, 201}, replay.text
        assert replay.json()['idempotent_replay'] is True
        assert replay.json().get('link', replay.json())['revision'] == link['revision']
        assert passed(read(case, link))['revision'] == reviewed_link['revision']
        assert table_counts(case.database) == before
        changed = {**request, 'reason': 'Same UUID but a changed operation'}
        assert submit(case, changed, alias, key=key).status_code == 409
        passed(case.reviewer.post('/v1/auth/users/' + case.creator_user['id'] + '/role', json={'is_admin': False}))
        assert submit(case, request, alias, key=key).status_code == 403
    finally:
        alias.close()


@pytest.mark.parametrize('key', ['', 'not-a-uuid', 'true'])
def test_write_requires_uuid_idempotency_key(case, key):
    response = case.creator.post(BASE + '/decisions', json=decision(case), headers={'Idempotency-Key': key})
    assert response.status_code in {400, 422}, response.text


def test_old_preview_event_revoke_restore_same_payload_cannot_pass_version_check(case):
    request = decision(case)
    event = case.event
    for action in ['revoke', 'restore']:
        event = passed(case.creator.post('/v1/test-events/' + event['id'] + '/state', json={
            'expected_revision': event['revision'], 'action': action,
            'operator': 'Synthetic event administrator', 'reason': 'Synthetic same-content ABA probe'}))
    assert event['fingerprint'] == case.event['fingerprint']
    assert event['revision_id'] != case.event['revision_id']
    assert_rejected(submit(case, request))


def test_reviewed_link_event_aba_invalidates_current_use_but_preserves_exact_original(case):
    link = reviewed(case)
    old = passed(read(case, link, revision=link['revision']))
    event = case.event
    for action in ['revoke', 'restore']:
        event = passed(case.creator.post('/v1/test-events/' + event['id'] + '/state', json={
            'expected_revision': event['revision'], 'action': action,
            'operator': 'Synthetic event administrator', 'reason': 'Synthetic same-content ABA probe'}))
    current = passed(read(case, link))
    assert current['eligibility'] == 'none' and current['stale_reasons']
    assert current['frozen_evidence'] == old['frozen_evidence']
    assert current['fingerprint'] == old['fingerprint']


def test_same_participant_key_replacement_is_not_same_test_object(case):
    link = reviewed(case)
    replacement = deepcopy(case.event_payload)
    replacement['event']['participants'][0]['source_designation'] = 'A different version in the same key'
    response = case.creator.put('/v1/test-events/' + case.event['id'],
        json={**replacement, 'expected_revision': 1})
    passed(response)
    current = passed(read(case, link))
    assert current['eligibility'] == 'none' and current['stale_reasons']


def test_participant_removed_then_reentered_preserves_old_history_without_reviving_review(case):
    link = reviewed(case)
    frozen = deepcopy(link['frozen_evidence'])
    removed = deepcopy(case.event_payload)
    removed['event']['participants'] = [row for row in removed['event']['participants'] if row['key'] != 'a']
    removed['event']['metrics'] = [row for row in removed['event']['metrics'] if row['key'] == 'wet']
    removed['event']['measurements'] = [row for row in removed['event']['measurements']
                                       if row['participant_key'] != 'a' and row['metric_key'] == 'wet']
    next_event = passed(case.creator.put('/v1/test-events/' + case.event['id'],
        json={**removed, 'expected_revision': 1}))
    missing = passed(read(case, link))
    assert missing['eligibility'] == 'none' and missing['stale_reasons']
    assert missing['frozen_evidence'] == frozen
    historical = passed(read(case, link, revision=link['revision']))
    assert historical['frozen_evidence'] == frozen and historical['eligibility'] == 'none'
    returned = passed(case.creator.put('/v1/test-events/' + case.event['id'],
        json={**case.event_payload, 'expected_revision': next_event['revision']}))
    assert returned['fingerprint'] == case.event['fingerprint']
    assert returned['revision_id'] != case.event['revision_id']
    current = passed(read(case, link))
    assert current['eligibility'] == 'none' and current['frozen_evidence'] == frozen


def test_stale_declaration_cannot_be_reaudited_as_if_current_event_were_confirmed(case):
    link = reviewed(case)
    event = case.event
    for action in ['revoke', 'restore']:
        event = passed(case.creator.post('/v1/test-events/' + event['id'] + '/state', json={
            'expected_revision': event['revision'], 'action': action,
            'operator': 'Synthetic event administrator', 'reason': 'Synthetic same-content event transition'}))
    proposal = deepcopy(case.proposal)
    proposal['selection']['event_revision_id'] = event['revision_id']
    request = decision(case, case.reviewer, proposal, action='review', link=link)
    assert_rejected(submit(case, request, case.reviewer))
    changed = decision(case, case.creator, proposal, action='revise', link=link)
    revised = link_view(submit(case, changed))
    assert revised['review_state'] == 'pending_review'
    refreshed = link_view(submit(case, decision(case, case.reviewer, proposal, action='review', link=revised), case.reviewer))
    assert refreshed['eligibility'] == 'conditional_reviewed_transcription'


def test_metadata_only_refresh_preserves_original_review_and_immutable_evidence(case):
    link = reviewed(case)
    original = deepcopy(link['frozen_evidence'])
    adopt(case, [case.tire], 'Synthetic new page observation, identical identity and facts')
    current = passed(read(case, link))
    assert current['eligibility'] == 'conditional_reviewed_transcription'
    assert current['frozen_evidence'] == original
    assert current['fingerprint'] == link['fingerprint']


def test_nonidentity_fact_refresh_is_not_falsely_called_identity_change(case):
    link = reviewed(case)
    changed = deepcopy(case.tire)
    changed['facts']['utqg_treadwear'] = 320
    adopt(case, [changed], 'Synthetic performance facts changed, exact identity unchanged')
    current = passed(read(case, link))
    assert current['frozen_evidence'] == link['frozen_evidence']
    assert current['eligibility'] == 'conditional_reviewed_transcription'


def test_lifecycle_revoke_restore_same_state_does_not_resurrect_old_review(case):
    from test_interest_governance_review import lifecycle
    link = reviewed(case)
    passed(lifecycle(case.creator, case.selection['variant_id'], [case.selection['tire_snapshot_id']]), 201)
    passed(lifecycle(case.creator, case.selection['variant_id'], [case.selection['tire_snapshot_id']],
        action='restore', revision=1), 201)
    current = passed(read(case, link))
    assert current['eligibility'] == 'none' and current['stale_reasons']


def test_identity_redirect_then_clear_same_terminal_state_does_not_resurrect_review(case):
    from test_identity_resolution import decision as identity_decision, post as identity_post
    link = reviewed(case)
    target = {**deepcopy(case.tire), 'manufacturer_product_code': 'SYNTHETIC-TARGET-OTHER'}
    result = adopt(case, [case.tire, target], 'Synthetic distinct exact identity candidates')
    target_id = next(row['id'] for row in result['variants'] if row['id'] != case.selection['variant_id'])
    snapshots = [case.selection['tire_snapshot_id'], result['provenance'][0]['snapshot_id']]
    passed(identity_post(case.creator, case.selection['variant_id'], identity_decision(
        case.creator, case.selection['variant_id'], target_id, snapshots)), 201)
    passed(identity_post(case.creator, case.selection['variant_id'], identity_decision(
        case.creator, case.selection['variant_id'], None, snapshots, action='clear')), 201)
    current = passed(read(case, link))
    assert current['eligibility'] == 'none' and current['stale_reasons']
    assert current['frozen_evidence'] == link['frozen_evidence']


def test_catalog_removal_reentry_same_member_cannot_resurrect_review(case):
    background = [{**deepcopy(case.tire), 'manufacturer_product_code': f'SYNTHETIC-BACKGROUND-{index}'}
                  for index in range(3)]
    adopt(case, [case.tire, *background], 'Synthetic four-row catalog')
    link = reviewed(case)
    adopt(case, background, 'Synthetic source temporarily removes selected exact member')
    adopt(case, [case.tire, *background], 'Synthetic source reenters same exact member')
    current = passed(read(case, link))
    assert current['eligibility'] == 'none' and current['stale_reasons']


@pytest.mark.parametrize('attack', ['raw', 'member', 'fact'])
def test_historical_source_corruption_is_rejected_without_returning_corrupt_proof(case, attack):
    link = reviewed(case)
    with case.database.engine.begin() as connection:
        if attack == 'raw':
            connection.execute(text('UPDATE snapshots SET body=:value WHERE id=:id'),
                {'value': 'CORRUPTED SOURCE PROOF', 'id': case.selection['tire_snapshot_id']})
        elif attack == 'member':
            with case.database.sessions() as db:
                members = deepcopy(db.get(Snapshot, case.selection['tire_snapshot_id']).parsed_variants)
            members[0]['manufacturer_product_code'] = 'CORRUPTED SOURCE PROOF'
            connection.execute(text('UPDATE snapshots SET parsed_variants=:value WHERE id=:id'),
                {'value': json.dumps(members), 'id': case.selection['tire_snapshot_id']})
        else:
            connection.execute(text('UPDATE fact_versions SET facts=:value WHERE id=:id'),
                {'value': json.dumps({'utqg_treadwear': 'CORRUPTED SOURCE PROOF'}),
                 'id': case.selection['fact_version_id']})
    response = read(case, link, revision=link['revision'])
    assert_rejected(response)
    assert 'CORRUPTED SOURCE PROOF' not in response.text


@pytest.mark.parametrize('table', ['test_sku_links', 'test_sku_link_revisions'])
@pytest.mark.parametrize('operation', ['update', 'delete', 'replace'])
def test_database_triggers_prevent_raw_sql_rewriting_append_only_bridge_history(case, table, operation):
    link = reviewed(case)
    with case.database.engine.connect() as connection:
        rows = connection.execute(text('SELECT * FROM ' + table)).mappings().all()
        original = [dict(row) for row in rows]
    identifier = original[0]['id']
    statement = {'update': 'UPDATE ' + table + ' SET id=id WHERE id=:id',
        'delete': 'DELETE FROM ' + table + ' WHERE id=:id',
        'replace': 'INSERT OR REPLACE INTO ' + table + ' SELECT * FROM ' + table + ' WHERE id=:id'}[operation]
    with pytest.raises(DBAPIError) as failure:
        with case.database.engine.begin() as connection:
            connection.execute(text(statement), {'id': identifier})
    assert 'immutable' in str(failure.value).lower() or 'append' in str(failure.value).lower()
    with case.database.engine.connect() as connection:
        assert [dict(row) for row in connection.execute(text('SELECT * FROM ' + table)).mappings()] == original
    assert passed(read(case, link))['eligibility'] == 'conditional_reviewed_transcription'


@pytest.mark.parametrize('kind', ['link', 'revision'])
@pytest.mark.parametrize('operation', ['update', 'delete'])
def test_orm_append_protection_blocks_mutation_before_flush(case, kind, operation):
    from tire_api.test_sku_link_models import TestSkuLink, TestSkuLinkRevision
    link = create(case)
    with case.database.sessions() as db:
        row = db.get(TestSkuLink, link['id']) if kind == 'link' else db.get(TestSkuLinkRevision, link['revision_id'])
        if operation == 'delete':
            db.delete(row)
        elif kind == 'link':
            row.participant_key = 'forged'
        else:
            row.reason = 'forged mutable history'
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
    assert passed(read(case, link))['revision'] == 1


def test_019_private_upgrade_is_additive_idempotent_and_does_not_backfill_existing_events(case):
    before = table_counts(case.database)
    with case.database.engine.begin() as connection:
        version = connection.execute(text("SELECT version FROM tire_schema_versions WHERE version LIKE '019%'")).scalar_one()
        connection.execute(text('DROP TABLE test_sku_link_revisions'))
        connection.execute(text('DROP TABLE test_sku_links'))
        connection.execute(text('DELETE FROM tire_schema_versions WHERE version=:version'), {'version': version})
    case.database.initialize()
    case.database.initialize()
    after = table_counts(case.database)
    assert after == before
    with case.database.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM tire_schema_versions WHERE version LIKE '019%'")).scalar_one() == 1
        triggers = list(connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('test_sku_links','test_sku_link_revisions')")))
        assert len(triggers) >= 6
    link = reviewed(case)
    assert link['eligibility'] == 'conditional_reviewed_transcription'


@pytest.mark.parametrize('field,value', [
    ('reason', 'OFFLINE CORRUPTED REASON'), ('declared_by_user_id', 'OFFLINE CORRUPTED ACTOR'),
    ('request_hash', '0' * 64), ('assertions', '[]'), ('before', '{}'), ('attestation', '{}'),
    ('frozen_evidence', '{}'), ('after', '{}'), ('materials', '[]')])
def test_full_revision_fingerprint_detects_corruption_beyond_payload_or_binding_hash(case, field, value):
    link = reviewed(case)
    # Deliberately model offline DB corruption only in this case's private DB.
    # This is separate from the raw-SQL trigger tests, which must remain enabled.
    with case.database.engine.begin() as connection:
        connection.execute(text('DROP TRIGGER test_sku_link_revisions_no_update'))
        connection.execute(text('UPDATE test_sku_link_revisions SET ' + field + '=:value WHERE id=:id'),
            {'value': value, 'id': link['revision_id']})
    response = read(case, link)
    assert_rejected(response)
    assert 'OFFLINE CORRUPTED' not in response.text


def test_same_scope_duplicate_create_and_concurrent_stale_revision_do_not_append(case):
    first, second = decision(case), decision(case)
    created = link_view(submit(case, first))
    assert submit(case, second).status_code == 409
    initial_review = decision(case, case.reviewer, action='review', link=created)
    link_view(submit(case, initial_review, case.reviewer))
    assert submit(case, initial_review, case.reviewer).status_code == 409
    assert passed(read(case, created))['revision'] == 2


def test_same_idempotency_uuid_is_scoped_by_stable_actor_not_globally(case):
    key = str(uuid4())
    created = link_view(submit(case, decision(case), key=key))
    request = decision(case, case.reviewer, action='review', link=created)
    link = link_view(submit(case, request, case.reviewer, key=key))
    assert link['revision'] == 2 and link['eligibility'] == 'conditional_reviewed_transcription'


@pytest.mark.parametrize('field,value', [('expected_revision', True), ('expected_revision', '0'),
    ('acknowledged', 1), ('acknowledged', False), ('declaration_revision_id', 'forged'),
    ('confirmed_event_revision_id', 'forged'), ('confirmed_participant_hash', '0' * 64)])
def test_decision_fences_cannot_be_replaced_by_truthy_values_or_other_revision(case, field, value):
    request = decision(case)
    request[field] = value
    assert_rejected(submit(case, request))


def test_r70_model_fact_selection_boundary_stays_closed_after_reviewed_bridge(case):
    from tire_api.ai_analysis import grounded_answer
    from tire_api.ai_evidence import PackBuilder
    reviewed(case)
    builder = PackBuilder()
    builder.add(kind='manual_test_independent', label='Synthetic test with an audited supplied-material link',
        provenance={'event_id': case.event['id'], 'revision': 1, 'verification_status': 'unverified'},
        values={'Synthetic source score': {'participant_key': 'a', 'raw_value': '38.00'}}, private=True)
    pack = SimpleNamespace(payload={'facts': builder.facts, 'evidence': builder.evidence,
                                   'conflicts': [], 'source_state': 'snapshot'}, data_state='local_snapshot')
    fact = builder.facts[0]
    for claim_type, free_text in [('inference', 'Recommend the exact SKU'), ('fact', 'Recommend this SKU')]:
        body = {'claims': [{'type': claim_type, 'text': free_text,
            'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}], 'uncertainty': ''}
        with pytest.raises(ValueError):
            grounded_answer(json.dumps(body), pack)
