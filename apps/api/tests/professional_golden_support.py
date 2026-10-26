"""Private HTTP capture adapter; never reads the case's independently authored oracle.

The caller owns an isolated application, environment and I/O fences. Only catalog
fixtures are seeded directly; all event, material, bridge and candidate operations
use the production HTTP routes. Two synthetic accounts are not human review.
"""
from copy import deepcopy
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from admin_support import register_admin
from test_fitment_relations import seed_tire, seed_vehicle
from tire_api.db import Snapshot, TireVariant
from tire_api.professional_golden_checks import json_sha256, load_case


ROOT = Path(__file__).resolve().parents[3]


def _body(response, status=200):
    if response.status_code != status:
        # Do not put rejected request bodies, accounts or cookies into receipts.
        raise ValueError('professional_golden_setup_http_' + str(response.status_code))
    return response.json()


def _observe(client, operation, path, request=None):
    method = 'GET' if operation == 'r71_current' else 'POST'
    if method == 'GET':
        response = client.get(path)
    else:
        headers = {'Idempotency-Key': str(uuid4())} if operation == 'r71_decision' else {}
        response = client.post(path, json=request, headers=headers)
    body = response.json()
    return {'operation': operation, 'method': method, 'path': path,
        'request_body': deepcopy(request), 'request_sha256': json_sha256(request),
        'http_status': response.status_code, 'response_body': body,
        'response_sha256': json_sha256(body)}


def _decision(proposal, preview):
    return {**deepcopy(proposal), 'expected_revision': preview['revision'],
        'expected_fingerprint': preview['fingerprint'],
        'declaration_revision_id': preview['declaration_revision_id'],
        'operator': 'Synthetic engineering evaluator',
        'reason': 'Project-authored contract exercise; no human Golden qualification',
        'acknowledged': True,
        'opened_materials': [{'document_id': material['document_id'], 'raw_hash': material['raw_hash'],
            'metadata_hash': material['metadata_hash']} for material in preview['material_evidence']],
        'confirmed_event_revision_id': preview['confirmed_event_revision_id'],
        'confirmed_participant_hash': preview['confirmed_participant_hash']}


def _proposal(literal, attempt, event, skus, materials):
    sku = skus[attempt['sku_label']]
    definitions = {m['material_label']: m for m in literal['materials']}
    return {'mode': 'history', 'action': 'create', 'link_id': None,
        'selection': {'event_id': event['id'], 'event_revision_id': event['revision_id'],
            'participant_key': attempt['participant_key'], 'variant_id': sku['variant_id'],
            'tire_snapshot_id': sku['tire_snapshot_id'], 'fact_version_id': sku['fact_version_id']},
        'materials': [{'document_id': materials[label]['document_id'],
            'expected_raw_hash': materials[label]['raw_sha256'],
            'expected_metadata_hash': materials[label]['metadata_sha256'],
            'event_locator': attempt['event_locator'], 'participant_locator': attempt['participant_locator'],
            'rights': {key: definitions[label]['rights'][key] for key in
                ('rights_holder', 'basis', 'store_original', 'workspace_reopen', 'quote_identifiers')}}
            for label in attempt['material_labels']],
        'assertions': [{**{key: claim[key] for key in ('field', 'material_value', 'page', 'region', 'quote')},
            'material_document_id': materials[claim['material_label']]['document_id']}
            for claim in attempt['assertions']], 'evidence_level': attempt['evidence_level']}


def run_private_case(client, case, execution):
    """Capture an explicit synthetic case in the caller's separately fenced private app."""
    literal = load_case(case).model_dump(mode='json', by_alias=True)
    data = literal['input']
    if data['mode'] != 'private_http' or any(m['origin'] != 'synthetic' for m in literal['materials']):
        raise ValueError('professional_golden_private_synthetic_case_required')
    database = client.app.state.database
    actual_path = Path(database.engine.url.database or '').resolve()
    configured = [make_url(os.environ.get(name, 'sqlite://'))
                  for name in ('TIRE_DATABASE_URL', 'DATABASE_URL')]
    if (database.engine.url.get_backend_name() != 'sqlite'
            or not database.engine.url.database or database.engine.url.database == ':memory:'
            or any(url.get_backend_name() != 'sqlite' or not url.database
                or Path(url.database).resolve() != actual_path for url in configured)
            or os.environ.get('TI_AI_ENABLED') != '0' or os.environ.get('TI_EMBEDDINGS_ENABLED') != '0'):
        raise ValueError('professional_golden_private_environment_required')
    private_root = Path(database.engine.url.database).resolve().parent
    if any(not Path(os.environ.get(name, '')).resolve().is_relative_to(private_root)
           for name in ('TI_OBJECT_STORE_ROOT', 'TI_PARSER_BUNDLE_ROOT')):
        raise ValueError('professional_golden_private_storage_required')
    register_admin(client)
    session = client.cookies['tire_local_session']
    vehicle_snapshot = seed_vehicle(database, session)
    skus = {}
    for index, sku in enumerate(data['skus']):
        variant_id, snapshot_id, fact_id = seed_tire(database, session, deepcopy(sku['value']),
            source='synthetic-professional-golden-' + str(index))
        with database.sessions() as db:
            snapshot = db.get(Snapshot, snapshot_id)
            variant = db.get(TireVariant, variant_id)
            member = next(row for row in snapshot.parsed_variants if row['id'] == variant_id)
            skus[sku['sku_label']] = {'sku_label': sku['sku_label'], 'variant_id': variant_id,
                'tire_snapshot_id': snapshot_id, 'fact_version_id': fact_id,
                'snapshot_member': deepcopy(member), 'identity': deepcopy(variant.identity)}
    candidate = data['candidate']
    selection = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle_snapshot,
        'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option',
        'axle': candidate['axle'] if candidate is not None else 'front'}
    if candidate is not None:
        from test_fitment_relations import decision as relation_decision, post as relation_post
        for label in candidate['reviewed_fitment_sku_labels']:
            sku_selection = {**selection, **{key: skus[label][key] for key in
                ('variant_id', 'tire_snapshot_id', 'fact_version_id')}}
            created = _body(relation_post(client, relation_decision(client, sku_selection)), 201)['relation']
            _body(relation_post(client, relation_decision(client, sku_selection, 'review', created['id'])), 201)
    created_event = _body(client.post('/v1/test-events', json={'event': data['event'],
        'operator': 'Synthetic engineering evaluator', 'reason': 'Independently authored synthetic case input'}), 201)
    event = _body(client.get('/v1/test-events/' + created_event['id'] + '?mode=history'))
    event_binding = {key: event[key] for key in ('id', 'revision_id', 'revision', 'fingerprint')}
    materials = {}
    for material in literal['materials']:
        original = material['original']
        path = (ROOT / original['path']).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('professional_golden_material_path_invalid')
        with path.open('rb') as stream:
            raw = stream.read(8_388_609)
        if (len(raw) > 8_388_608 or len(raw) != original['byte_count']
                or hashlib.sha256(raw).hexdigest() != original['sha256']):
            raise ValueError('professional_golden_material_binding_invalid')
        metadata = {'title': material['title'], 'source_url': material['source_reference_url'],
            'operator': 'Synthetic engineering evaluator', 'rights_basis': material['rights']['basis']}
        uploaded = _body(client.post('/v1/documents', content=raw,
            headers={'content-type': 'application/pdf', 'x-evidence-metadata':
                base64.b64encode(json.dumps(metadata, ensure_ascii=False).encode()).decode()}), 201)
        listed = _body(client.get('/v1/test-sku-links/materials?mode=history'))['items']
        receipt = next(row for row in listed if row['id'] == uploaded['id'])
        materials[material['material_label']] = {'material_label': material['material_label'],
            'document_id': uploaded['id'], 'raw_sha256': receipt['raw_hash'],
            'byte_count': receipt['byte_count'], 'metadata_sha256': receipt['metadata_hash']}
    other = TestClient(client.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    runs = []
    try:
        reviewer = register_admin(other, 'synthetic-golden-reviewer')['user']
        _body(client.post('/v1/auth/users/' + reviewer['id'] + '/role', json={'is_admin': True}))
        for attempt in data['bridge_attempts']:
            proposal = _proposal(literal, attempt, event_binding, skus, materials)
            preview = _observe(client, 'r71_preview', '/v1/test-sku-links/preview', proposal)
            decisions, current = [], None
            if preview['http_status'] == 200 and preview['response_body']['can_submit'] is True:
                decision = _observe(client, 'r71_decision', '/v1/test-sku-links/decisions',
                    _decision(proposal, preview['response_body']))
                decisions.append(decision)
                if decision['http_status'] == 201:
                    link_id = decision['response_body']['link']['id']
                    for action in (['review'] if attempt['review'] else []) + (['revoke'] if attempt['revoke'] else []):
                        action_proposal = {**proposal, 'action': action, 'link_id': link_id}
                        refreshed = _body(other.post('/v1/test-sku-links/preview', json=action_proposal))
                        decisions.append(_observe(other, 'r71_decision', '/v1/test-sku-links/decisions',
                            _decision(action_proposal, refreshed)))
                    current = _observe(client, 'r71_current', '/v1/test-sku-links/' + link_id + '?mode=history')
            runs.append({'attempt_id': attempt['attempt_id'], 'preview': preview,
                'decisions': decisions, 'current': current})
        candidate_result = None
        if candidate is not None:
            preference = _body(client.put('/v1/driving-preferences', json={
                'expected_revision': 0, 'weights': candidate['preference_weights']}))
            by_attempt = {run['attempt_id']: run for run in runs}
            refs = []
            for attempt_id in candidate['attempt_ids']:
                current = by_attempt[attempt_id]['current']
                if current is None or current['http_status'] != 200:
                    raise ValueError('professional_golden_candidate_current_unavailable')
                link = current['response_body']
                refs.append({'variant_id': link['selection']['variant_id'], 'link_id': link['id'],
                    'expected_link_revision_id': link['revision_id'], 'expected_link_revision': link['revision'],
                    'expected_link_fingerprint': link['fingerprint']})
            request = {'selection': selection, 'expected_event_revision_id': event['revision_id'],
                'expected_event_revision': event['revision'], 'expected_event_fingerprint': event['fingerprint'],
                'expected_preference_revision': preference['revision'],
                'expected_preference_fingerprint': preference['fingerprint'],
                'candidates': refs, 'metric_dimensions': candidate['metric_dimensions']}
            candidate_result = _observe(client, 'r75_interpretation',
                '/v1/test-events/' + event['id'] + '/candidate-interpretation?mode=history', request)
    finally:
        other.close()
    return {'schema': 'professional-golden-actual@1', 'case_id': literal['case_id'],
        'input_sha256': json_sha256(data), 'execution': deepcopy(execution),
        'event_binding': event_binding, 'event_snapshot': event,
        'sku_bindings': list(skus.values()), 'material_bindings': list(materials.values()),
        'bridge_results': runs, 'candidate_result': candidate_result, 'source_review_result': None}
