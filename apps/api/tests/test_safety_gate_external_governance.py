"""Source-specific Safety Gate evidence binding through the existing license ledger."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from tire_api.db import utcnow
from tire_api.external_fact_governance import GovernanceError, GovernanceStore
from tire_api.external_fact_models import ExternalFactGrantRevision
from tire_api.safety_gate import SafetyGateVerification
from admin_support import ADMIN_PASSWORD, register_admin
from test_safety_gate import context, run

TERMS = b'Synthetic fixture rights only; not permission for real third-party data.'


def proposal(result, *, fields=None):
    provenance = result['provenance'][0]
    return {'schema': 'external-fact-governance-request@1', 'action': 'approve', 'grant_id': 'synthetic-safety-grant',
        'reason': 'Synthetic ledger boundary test', 'source_id': 'eu-safety-gate',
        'coverage': {'observations': [{key: provenance[key] for key in ('snapshot_id', 'raw_hash', 'parser_version')}],
            'field_keys': fields or ['identity.alert_id', 'facts.brand']},
        'rights': {'holder': 'Synthetic author', 'basis': 'Self-authored test XML'},
        'validity': {'not_before': (utcnow()-timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'not_after': None},
        'license_reference': 'https://example.org/synthetic-license', 'rights_reviewed': True}


def approve(store, actor, request):
    prepared = store.preview(actor, request, terms=TERMS)
    return store.append(actor, request, terms=TERMS, expected_revision=prepared['expected_revision'],
        expected_head=prepared['expected_head'], expected_preview_fingerprint=prepared['fingerprint'],
        idempotency_key=str(uuid4()))


def test_safety_gate_approval_binds_its_own_snapshot_and_verification_tables(context):
    client, _adapter, database = context
    register_admin(client)
    result = run(client)
    store = GovernanceStore(database.engine)
    actor = store.authenticate('admin', ADMIN_PASSWORD)
    saved = approve(store, actor, proposal(result))
    assert saved['current']['state'] == 'approved'
    with database.sessions() as db:
        row = db.scalar(select(ExternalFactGrantRevision))
        binding = row.binding_receipts[0]
        verification = db.get(SafetyGateVerification, binding['verification_id'])
        assert verification is not None and verification.query_id == result['query_id']
        assert binding['snapshot_id'] == result['provenance'][0]['snapshot_id']
        assert binding['raw_hash'] == result['provenance'][0]['raw_hash']


@pytest.mark.parametrize('field,value', [('raw_hash', '0'*64), ('parser_version', 'other@1'), ('snapshot_id', 'missing')])
def test_wrong_observation_never_creates_permission(context, field, value):
    client, _adapter, database = context
    register_admin(client)
    result = run(client)
    store = GovernanceStore(database.engine)
    actor = store.authenticate('admin', ADMIN_PASSWORD)
    request = proposal(result)
    request['coverage']['observations'][0][field] = value
    with pytest.raises(GovernanceError, match='observation_binding_invalid'):
        store.preview(actor, request, terms=TERMS)


@pytest.mark.parametrize('corruption', ['body', 'verification', 'query', 'document', 'parser_identity', 'query_key', 'source_url'])
def test_corrupted_formal_evidence_is_rejected(context, corruption):
    client, _adapter, database = context
    register_admin(client)
    result = run(client)
    with database.sessions() as db:
        if corruption == 'body':
            db.execute(text('UPDATE safety_gate_snapshots SET body = :body'), {'body':'tampered'})
        elif corruption == 'verification':
            db.execute(text('UPDATE safety_gate_verifications SET status = :status'), {'status':'unavailable'})
        elif corruption == 'query':
            db.execute(text('UPDATE query_runs SET state = :state WHERE id = :id'), {'state':'consent_required','id':result['query_id']})
        elif corruption == 'document':
            db.execute(text('UPDATE safety_gate_snapshots SET document_hash = :hash'), {'hash':'0'*64})
        elif corruption == 'parser_identity':
            db.execute(text('UPDATE safety_gate_verifications SET parser_identity = :identity'), {'identity':'{"tampered":true}'})
        elif corruption == 'query_key':
            db.execute(text('UPDATE safety_gate_verifications SET query_key = :key'), {'key':'0'*64})
        else:
            db.execute(text('UPDATE safety_gate_snapshots SET source_url = :url'), {'url':'https://example.org/wrong'})
        db.commit()
    store = GovernanceStore(database.engine)
    with pytest.raises(GovernanceError, match='observation_binding_invalid'):
        store.preview(store.authenticate('admin', ADMIN_PASSWORD), proposal(result), terms=TERMS)


def test_index_cannot_be_licensed_as_report_alerts(context):
    client, _adapter, database = context
    register_admin(client)
    result = run(client, {'operation':'reports'})
    store = GovernanceStore(database.engine)
    with pytest.raises(GovernanceError, match='observation_binding_invalid'):
        store.preview(store.authenticate('admin', ADMIN_PASSWORD), proposal(result), terms=TERMS)


def test_not_modified_report_can_bind_latest_successful_verification(context):
    client, adapter, database = context
    register_admin(client)
    first = run(client)
    adapter.not_modified = True
    latest = run(client)
    assert latest['data_state'] == 'live_verified_304'
    assert latest['provenance'][0]['snapshot_id'] == first['provenance'][0]['snapshot_id']
    store = GovernanceStore(database.engine)
    approve(store, store.authenticate('admin', ADMIN_PASSWORD), proposal(latest))
    with database.sessions() as db:
        binding = db.scalar(select(ExternalFactGrantRevision)).binding_receipts[0]
        assert binding['query_id'] == latest['query_id']
        assert db.get(SafetyGateVerification, binding['verification_id']).status == 'not_modified'
