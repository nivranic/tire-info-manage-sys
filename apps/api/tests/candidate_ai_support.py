"""R77 synthetic owned catalog only: no TestEvent, professional material or R71 bridge."""
from copy import deepcopy
from datetime import timedelta
import json
import hashlib
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

from admin_support import register_admin
from test_fitment_relations import (NoNetworkRegistry, seed_tire, seed_vehicle, tire_payload,
    decision as relation_decision, post as relation_post)
from tire_api.db import utcnow


def ok(response, status=200):
    assert response.status_code == status, (response.status_code, response.json().get('detail'))
    return response.json()


class ControlledCandidateAdapter:
    def __init__(self):
        self.calls = []
        self.text = json.dumps({'decision': 'abstain', 'selections': [], 'uncertainty_codes': []})

    async def generate(self, config, body):
        self.calls.append(deepcopy(body))
        return {'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
            'provider_response_id': 'synthetic-r77-controlled', 'text': self.text, 'error': None}


def seed_candidate_ai(client):
    """Caller has bound all configuration and I/O guards before app import/lifespan."""
    database = client.app.state.database
    user = ok(client.get('/v1/auth/me'))['user']
    if user is None:
        user = register_admin(client)['user']
    session = client.cookies['tire_local_session']
    vehicle = seed_vehicle(database, session)
    variants, selections = [], []
    for index in range(2):
        value = tire_payload(manufacturer_product_code='SYNTHETIC-R77-' + str(index),
            facts={'product_code_type': 'MSPN'})
        identifier, tire, fact = seed_tire(database, session, value, source='synthetic-owned-r77-' + str(index))
        selected = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle,
            'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front',
            'variant_id': identifier, 'tire_snapshot_id': tire, 'fact_version_id': fact}
        created = ok(relation_post(client, relation_decision(client, selected)), 201)['relation']
        ok(relation_post(client, relation_decision(client, selected, 'review', created['id'])), 201)
        variants.append(identifier)
        selections.append(selected)
    weights = {'dry': 25, 'wet': 25, 'quiet': 15, 'comfort': 10, 'wear': 15, 'energy': 5, 'appearance': 5}
    preference = ok(client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': weights}))
    selection = {key: selections[0][key] for key in ('vehicle_id', 'vehicle_snapshot_id', 'trim_id', 'wheel_option_id', 'axle')}
    adapter = ControlledCandidateAdapter()
    client.app.state.ai_adapter = adapter
    return SimpleNamespace(client=client, app=client.app, database=database, user=user, adapter=adapter,
        selection=selection, selections=selections, variants=variants, preference=preference)


def prepare_payload(case):
    return {'selection': case.selection, 'expected_preference_revision': case.preference['revision'],
        'expected_preference_fingerprint': case.preference['fingerprint'], 'variant_ids': case.variants,
        'question': 'SYNTHETIC: choose a specification option for further checking, with no performance conclusion'}


def prepare(case):
    return ok(case.client.post('/v1/ai/candidate-preparations', json=prepare_payload(case)))


def grant_payload(dependency, *, revision=0, action='grant'):
    if action == 'revoke':
        return {'dependency_id': dependency['id'], 'provider': 'openai_responses', 'expected_revision': revision,
            'action': action, 'acknowledged': True, 'revocation_note': 'Synthetic scope revocation for engineering verification'}
    return {'dependency_id': dependency['id'], 'provider': 'openai_responses', 'expected_revision': revision,
        'action': action, 'rights_holder': 'Project synthetic fixture authors',
        'license_basis_url': 'https://fixture.invalid/project-authored-r77-license',
        'license_basis_note': 'Project-authored synthetic catalog and relation bytes; permission for this engineering test only',
        'license_evidence_sha256': hashlib.sha256((Path(__file__).parent / 'fixtures/candidate_ai/SYNTHETIC-LICENSE.txt').read_bytes()).hexdigest(),
        'expires_at': (utcnow() + timedelta(hours=1)).isoformat(), 'acknowledged': True}


def grant_all(case, preparation):
    for dep in preparation['dependencies']:
        ok(case.client.post('/v1/ai/candidate-preparations/' + preparation['preparation_id'] + '/authorizations',
            json=grant_payload(dep)))


def submit_payload(preparation):
    return {'preparation_id': preparation['preparation_id'], 'consent_hash': preparation['consent_hash'],
        'allow_external_processing': True}


def configured_environment(monkeypatch, private_root):
    private_root = Path(private_root)
    private_root.mkdir(parents=True, exist_ok=False)
    url = 'sqlite:///' + (private_root / 'p.db').as_posix()
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
            monkeypatch.delenv(name, raising=False)
    for name, value in {'TIRE_DATABASE_URL': url, 'DATABASE_URL': url,
            'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(private_root / 'o'),
            'TI_PARSER_BUNDLE_ROOT': str(private_root / 'b'), 'TI_AI_ENABLED': '1',
            'TI_AI_PROVIDER': 'openai_responses', 'TI_OPENAI_MODEL': 'synthetic-r77-model',
            'TI_OPENAI_API_KEY': secrets.token_urlsafe(18), 'TI_AI_ALLOW_PRIVATE': '1',
            'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0'}.items():
        monkeypatch.setenv(name, value)
    return url
