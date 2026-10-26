"""Private, synthetic two-SKU closure for candidate interpretation tests.

These materials are authored fixtures, never professional-source or human-Golden
evidence. Only public HTTP writes establish the reviewed relationships and links.
"""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, text

from admin_support import register_admin
from test_fitment_relations import (NoNetworkRegistry, decision as relation_decision,
    post as relation_post, seed_tire, seed_vehicle, tire_payload)
from test_test_events import PAYLOAD, create as create_event
from test_test_preference_routes import save_preference
from test_test_sku_links import (decision as bridge_decision, operation,
    post as bridge_post, second_admin, stored)
from tire_api.main import create_app


SELECTION_KEYS = ('vehicle_id', 'vehicle_snapshot_id', 'trim_id', 'wheel_option_id', 'axle')


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def business_counts(database):
    with database.engine.connect() as connection:
        return {name: connection.execute(text('SELECT COUNT(*) FROM "' + name + '"')).scalar_one()
                for name in inspect(connection).get_table_names() if 'session' not in name.lower()}


def reference(link):
    return {'variant_id': link['selection']['variant_id'], 'link_id': link['id'],
        'expected_link_revision_id': link['revision_id'], 'expected_link_revision': link['revision'],
        'expected_link_fingerprint': link['fingerprint']}


def request_body(case, **changes):
    return {'selection': {key: case.selections[0][key] for key in SELECTION_KEYS},
        'expected_event_revision_id': case.event['revision_id'],
        'expected_event_revision': case.event['revision'],
        'expected_event_fingerprint': case.event['fingerprint'],
        'expected_preference_revision': case.preference['revision'],
        'expected_preference_fingerprint': case.preference['fingerprint'],
        'candidates': [reference(link) for link in case.links],
        'metric_dimensions': [{'metric_key': 'wet', 'dimension': 'wet'},
            {'metric_key': 'noise', 'dimension': 'quiet'}, {'metric_key': 'dry', 'dimension': 'dry'}],
        **changes}


def interpret(case, payload=None, client=None, **changes):
    return (client or case.client).post('/v1/test-events/' + case.event['id']
        + '/candidate-interpretation?mode=history', json=payload or request_body(case, **changes))


@pytest.fixture
def candidate_case(tmp_path, monkeypatch):
    private_root = Path(os.environ.get('R75_TEST_STORAGE_ROOT', str(tmp_path)))
    storage = private_root / uuid4().hex[:8]
    storage.mkdir(parents=True, exist_ok=False)
    private_url = 'sqlite:///' + (storage / 'p.sqlite').as_posix()
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_')) or name in ('DATABASE_URL',)
                or name.lower().endswith('_proxy')):
            monkeypatch.delenv(name, raising=False)
    for name, value in {'TIRE_DATABASE_URL': private_url, 'DATABASE_URL': private_url,
            'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
            'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(storage / 'o'),
            'TI_PARSER_BUNDLE_ROOT': str(storage / 'b')}.items():
        monkeypatch.setenv(name, value)
    import aiohttp
    import httpx
    import socket
    import subprocess
    def prohibited(*_args, **_kwargs):
        raise AssertionError('candidate interpretation attempted network or child-process I/O')
    monkeypatch.setattr(aiohttp, 'ClientSession', prohibited)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', prohibited)
    monkeypatch.setattr(socket, 'create_connection', prohibited)
    monkeypatch.setattr(subprocess, 'Popen', prohibited)
    app = create_app(private_url, NoNetworkRegistry())
    with TestClient(app) as client:
        scenario = seed_candidate_scenario(client)
        try:
            yield scenario
        finally:
            scenario.reviewer.close()


def synthetic_pdf(tires):
    """An actual project-authored PDF whose text is explicitly synthetic."""
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    from tire_api.domain import VariantInput
    stream = BytesIO()
    canvas = Canvas(stream, pageCompression=0)
    canvas.setTitle('SYNTHETIC CONTRACT FIXTURE - NOT A REAL PUBLICATION')
    lines = ['SYNTHETIC CONTRACT FIXTURE - NOT A REAL PUBLICATION',
             'SYNTHETIC candidate interpretation contract fixture']
    for key, tire in zip(('a', 'b'), tires):
        lines.append('SYNTHETIC participant ' + key)
        lines.extend('SYNTHETIC ' + field + ' = ' + str(value)
                     for field, value in VariantInput.model_validate(tire).identity().items())
    canvas.setFont('Helvetica', 8)
    for index, line in enumerate(lines):
        canvas.drawString(30, 810 - index * 16, line)
    canvas.save()
    return stream.getvalue()


def seed_candidate_scenario(client, database=None, session=None):
    """Seed within the caller's private TestClient lifespan; close result.reviewer.

    Reuses an authenticated caller or registers the initial synthetic administrator.
    No credential value is returned or written to an artifact.
    """
    app = client.app
    database = database or app.state.database
    session = session or client.cookies.get('tire_local_session')
    storage = Path(database.engine.url.database).parent
    actor = ok(client.get('/v1/auth/me'))['user']
    if actor is None:
        actor = register_admin(client)['user']
    session = client.cookies['tire_local_session']
    vehicle = seed_vehicle(database, session)
    tires = [tire_payload(), tire_payload(manufacturer_product_code='SYNTHETIC-002')]
    selections = []
    relations = []
    for index, tire in enumerate(tires):
        variant, snapshot, fact = seed_tire(database, session, tire,
            source='synthetic-candidate-source-' + str(index))
        selected = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle,
            'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front',
            'variant_id': variant, 'tire_snapshot_id': snapshot, 'fact_version_id': fact}
        created = ok(relation_post(client, relation_decision(client, selected)), 201)['relation']
        relations.append(ok(relation_post(client,
            relation_decision(client, selected, 'review', created['id'])), 201)['relation'])
        selections.append(selected)
    data = deepcopy(PAYLOAD)
    data['event']['title'] = 'SYNTHETIC candidate interpretation contract fixture'
    data['event']['tested_size'] = tires[0]['size']
    for participant, tire in zip(data['event']['participants'], tires):
        participant.update(brand=tire['brand'], model=tire['model'])
    data['event']['metrics'].append({'key': 'dry', 'label': 'Synthetic zero ties', 'unit': 'points',
        'protocol': 'Synthetic dry tie method', 'direction': 'higher'})
    data['event']['measurements'].extend([
        {'participant_key': key, 'metric_key': 'dry', 'raw_value': value, 'source_rank': rank,
         'evidence_span': 'SYNTHETIC signed zero only', 'evidence_locator': 'Synthetic dry row ' + key}
        for key, value, rank in [('a', '-0', None), ('b', '0', 8)]])
    event = create_event(client, data)
    metadata = {'title': 'SYNTHETIC identity material, not a professional test',
        'source_url': event['event']['source_url'], 'operator': 'Synthetic fixture author',
        'rights_basis': 'Project-authored synthetic bytes; local contract testing only'}
    document = ok(client.post('/v1/documents',
        content=synthetic_pdf(tires),
        headers={'content-type': 'application/pdf', 'x-evidence-metadata':
            base64.b64encode(json.dumps(metadata).encode()).decode()}), 201)
    material = next(row for row in ok(client.get('/v1/test-sku-links/materials?mode=history'))['items']
                    if row['id'] == document['id'])
    reviewer = second_admin(client)
    proposals, links = [], []
    for selected, participant in zip(selections, event['event']['participants']):
        bridge_selection = {key: selected[key] for key in
                            ('variant_id', 'tire_snapshot_id', 'fact_version_id')}
        bridge_selection.update(event_id=event['id'], event_revision_id=event['revision_id'],
                                participant_key=participant['key'])
        proposal = {'mode': 'history', 'action': 'create', 'link_id': None,
            'selection': bridge_selection, 'materials': [], 'assertions': [],
            'evidence_level': 'manual_assertion'}
        frozen = ok(client.post('/v1/test-sku-links/preview', json=proposal))
        identity = frozen['frozen_evidence']['tire']['identity']
        locator = {'page': 1, 'region': 'synthetic participant ' + participant['key'],
                   'quote': 'SYNTHETIC participant ' + participant['key']}
        proposal.update(materials=[{'document_id': document['id'],
            'expected_raw_hash': material['raw_hash'], 'expected_metadata_hash': material['metadata_hash'],
            'event_locator': locator, 'participant_locator': locator,
            'rights': {'rights_holder': 'Project synthetic fixture authors',
                'basis': 'Project-authored synthetic local contract testing', 'store_original': True,
                'workspace_reopen': True, 'quote_identifiers': True}}],
            assertions=[{'field': key, 'material_document_id': document['id'], 'material_value': value,
                'page': 1, 'region': 'synthetic identity row ' + key,
                'quote': 'SYNTHETIC ' + key + ' = ' + str(value)} for key, value in identity.items()],
            evidence_level='source_explicit_identifiers_in_supplied_material')
        declared = stored(client, proposal)
        reviewed = ok(bridge_post(reviewer,
            bridge_decision(reviewer, operation(proposal, declared['id'], 'review'))), 201)['link']
        assert reviewed['eligibility'] == 'conditional_reviewed_transcription', reviewed
        proposals.append(proposal)
        links.append(reviewed)
    return SimpleNamespace(app=app, client=client, reviewer=reviewer, database=database,
        actor=actor, session=session, selections=selections, relations=relations, tires=tires,
        event=event, event_payload=data, preference=save_preference(client), proposals=proposals,
        links=links, document=document, storage=storage)
