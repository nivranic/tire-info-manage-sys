"""Private synthetic packets preserve old evidence and refuse stale identity contracts."""
from copy import deepcopy

import pytest

from tire_api.ai_models import AIEvidencePack, AIRequest
from tire_api.domain import digest
from test_ai import analyze, count, historical_pack, setup


@pytest.mark.parametrize('changed', ['missing', 'different_key', 'incomplete'])
def test_old_or_different_frozen_contract_requires_new_pack_without_model_call(setup, changed):
    client, _registry, model, database = setup
    fresh = historical_pack(client)
    evidence = fresh['evidence'][0]
    assert evidence['identity_contract']['state'] == 'current'
    assert evidence['identity_contract']['schema'] == 'variant-identity@2'
    with database.sessions() as db:
        original = db.get(AIEvidencePack, fresh['id'])
        content = deepcopy(original.payload)
        if changed == 'missing':
            content['evidence'][0].pop('identity_contract')
        elif changed == 'different_key':
            content['evidence'][0]['identity_contract']['current_key'] = '0' * 64
        else:
            content['evidence'][0]['identity_contract'].pop('identity_status')
        old = AIEvidencePack(actor_session_id=original.actor_session_id, mode=original.mode,
            data_state=original.data_state, privacy_class=original.privacy_class, payload=content,
            fingerprint=digest(content), expires_at=original.expires_at)
        db.add(old)
        db.commit()
        old_id = old.id
    response = analyze(client, {'id': old_id})
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'ai_evidence_identity_contract_stale'
    assert model.calls == [] and count(database, AIRequest) == 0
    saved = client.get(f'/v1/ai/evidence-packs/{old_id}?mode=history').json()
    assert saved['evidence'] == content['evidence']
    assert saved['fingerprint'] == digest(content)
    # Re-preparing or retaining a correctly bound new packet remains usable.
    response = analyze(client, fresh)
    assert response.status_code == 200, response.text
    assert len(model.calls) == 1 and response.json()['state'] == 'completed'
