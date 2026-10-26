"""Private binary history/Golden governance; actual children, no online acceptance.

S2 is an existing reviewed local input. Temporary packages, deployments and
Golden signatures are synthetic fixtures, never production or human acceptance.
Legacy hash vectors below freeze the pre-R90 serialized algorithms, not a
pre-change runtime result. Only the managed runner may import/execute this file.
"""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from tire_api import captures, golden, parser_releases, parser_runtime as runtime, reparse
from tire_api.db import QueryRun, RawCapture, uid
from tire_api.domain import digest, stable_json
from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.knowledge_models import KnowledgeDocument
from tire_api.parser_release_models import (ParserBundle, ParserDeploymentRevision, ParserExecution,
    ParserSelection)
from tire_api.reparse_models import ReparseRun
from tire_api.vehicle_raw import PDF_URL, PROVENANCE_KEYS, VehicleRawIntegrityError
from tire_api.vehicles import (VehicleSnapshot, VehicleVerification, WheelFitment, fitment_fact_hash)
from test_golden import SIGNED, evaluation_reference, freeze_cases, post, sign_case
from test_vehicle_pdf_runtime import reviewed_pdf
from test_vehicle_binary_ingestion import (SOURCE, VEHICLE, adopt, count, damage_snapshot,
    private, private_mapping_revision)


FACTS = (QueryRun, RawCapture, ParserExecution, VehicleSnapshot, VehicleVerification,
         WheelFitment, InterestEvent, InterestNotification, KnowledgeDocument)


def totals(ctx):
    return {model.__tablename__: count(ctx, model) for model in FACTS}


def original(ctx, accepted):
    with ctx.database.sessions() as db:
        cap = db.scalar(select(RawCapture).where(RawCapture.query_id == accepted['query_id']))
        selected = db.get(ParserSelection, cap.query_id)
        return cap.id, selected.bundle_id


def request_body(ctx, capture_id, bundle_id):
    with ctx.database.sessions() as db:
        descriptor = db.get(ParserBundle, bundle_id).descriptors[SOURCE]
        return {'mode': 'history', 'capture_id': capture_id, 'bundle_id': bundle_id,
                'parser_version': descriptor['parser_version'], 'parser_digest': descriptor['parser_digest']}


def history(ctx, capture_id, bundle_id, *, key=None):
    return post(ctx.client, '/v1/reparse/runs', request_body(ctx, capture_id, bundle_id), key)


def seed_raw(ctx, raw):
    """Durable raw plus a real completed/failed original child, without facts."""
    with ctx.database.sessions() as db:
        run = QueryRun(id=uid(), session_id=ctx.session_id, source_id=SOURCE,
            query={'vehicle_id': VEHICLE}, query_key=digest({'vehicle_id': VEHICLE}), fallback_policy='never')
        db.add(run)
        db.commit()
        selected = parser_releases.pin_selection(db, run.id, SOURCE)
        observation = {'body': raw, 'body_encoding': 'binary', 'url': PDF_URL,
            'content_type': 'application/pdf', 'parser_version': selected['parser_version'],
            'parser_identity': {key: selected[key] for key in ('bundle_id', 'parser_digest', 'deployment_revision')}}
        db.commit()
        captures.before_parse_recorder(db, run)(observation)
        assert not db.in_transaction()
        try:
            parsed = asyncio.run(runtime.parse_isolated(SOURCE, raw, {'vehicle_id': VEHICLE},
                selected['parser_version'], selected['parser_digest'],
                bundle_manifest=selected['bundle_manifest'], deployment_revision=selected['deployment_revision']))
            outcome = {'state': 'completed', 'error_code': None, 'receipt': parsed['receipt']}
        except runtime.ParserRunError as error:
            outcome = {'state': 'failed', 'error_code': error.code, 'receipt': error.receipt}
        parser_releases.record_execution(db, run.id, outcome)
        db.commit()
        cap = db.scalar(select(RawCapture).where(RawCapture.query_id == run.id))
        return cap.id, selected['bundle_id'], outcome


def golden_set(ctx, capture_id, payload, *, mismatch=False):
    expected = {key: deepcopy(payload[key]) for key in ('vehicle', 'trims', 'fitments')}
    if mismatch:
        expected['vehicle']['model'] += ' synthetic mismatch'
    response = post(ctx.client, '/v1/golden/cases', {'kind': 'vehicle', 'source_id': SOURCE,
        'title': 'Synthetic private S2 assertions', 'capture_id': capture_id,
        'evidence_note': 'Synthetic private signature only; no external human Golden qualification.',
        'expected': expected, 'expected_revision': 0, 'expected_fingerprint': None, **SIGNED})
    assert response.status_code == 201, response.text
    case = sign_case(ctx.client, response.json())
    return freeze_cases(ctx.client, [case]), case


def evaluate(ctx, capture_id, bundle_id, frozen=None):
    with ctx.database.sessions() as db:
        revision = parser_releases.current_deployment(db, SOURCE).revision
    return post(ctx.client, '/v1/parser-evaluations', {'mode': 'history', 'source_id': SOURCE,
        'target_bundle_id': bundle_id, 'capture_ids': [capture_id], 'expected_deployment_revision': revision,
        **(evaluation_reference(frozen) if frozen else {})})


def approve(ctx, evaluation, **extra):
    return ctx.client.post('/v1/parser-evaluations/' + evaluation['id'] + '/reviews', json={
        'mode': 'history', 'expected_revision': evaluation['review_revision'], 'action': 'approve',
        'acknowledged': True, 'completion_fingerprint': evaluation['completion']['fingerprint'], **SIGNED, **extra})


def observe_child_transactions(ctx, monkeypatch, owner):
    parents = []
    reader = owner.checked_history_capture_bytes
    actual = runtime.parse_isolated
    def observed(db, capture, **kwargs):
        parents.append(db)
        return reader(db, capture, **kwargs)
    async def checked(*args, **kwargs):
        assert parents and all(not db.in_transaction() for db in parents)
        assert ctx.database.engine.pool.checkedout() == 0
        return await actual(*args, **kwargs)
    monkeypatch.setattr(owner, 'checked_history_capture_bytes', observed)
    monkeypatch.setattr(runtime, 'parse_isolated', checked)


def test_actual_s2_history_and_review_are_frozen_candidates_only(private, monkeypatch):
    ctx = private
    accepted = adopt(ctx)
    capture_id, bundle_id = original(ctx, accepted)
    before = totals(ctx)
    observe_child_transactions(ctx, monkeypatch, reparse)
    key = str(uuid4())
    response = history(ctx, capture_id, bundle_id, key=key)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['state'] == 'completed' and run['accepted_as_facts'] is False
    assert run['input']['body_encoding'] == 'binary'
    assert run['input']['original_mapping_status'] == 'not_attested'
    assert 'mapping_id' not in run['input'] and 'parse_provenance' not in run['input']
    block = run['completion']['candidate']['parse_provenance']
    assert set(block) == PROVENANCE_KEYS and block['bundle_id'] == bundle_id
    assert block['source_raw_hash'] == run['input']['raw_hash']
    assert run['completion']['receipt']['reaped'] and run['completion']['receipt']['exit_code'] == 0
    assert history(ctx, capture_id, bundle_id, key=key).json() == run
    reviewed = ctx.client.post('/v1/reparse/runs/' + run['id'] + '/reviews', json={
        'mode': 'history', 'expected_revision': 0, 'status': 'reviewed', **SIGNED})
    assert reviewed.status_code == 201 and totals(ctx) == before
    assert reviewed.json()['completion']['fingerprint'] == run['completion']['fingerprint']


def test_binary_requires_explicit_registered_bundle_before_reservation_or_child(private, monkeypatch):
    ctx = private
    accepted = adopt(ctx)
    capture_id, bundle_id = original(ctx, accepted)
    body = request_body(ctx, capture_id, bundle_id)
    body.pop('bundle_id')
    def forbidden(*_args, **_kwargs):
        raise AssertionError('missing bundle must not execute')
    monkeypatch.setattr(runtime, 'parse_isolated', forbidden)
    response = post(ctx.client, '/v1/reparse/runs', body)
    assert response.status_code == 422 and response.json()['detail'] == {'code': 'binary_reparse_bundle_required'}
    assert count(ctx, ReparseRun) == 0


def test_unknown_original_failed_without_snapshot_can_attempt_actual_history_child(private):
    ctx = private
    capture_id, bundle_id, outcome = seed_raw(ctx, b'%PDF-1.7\nsynthetic unknown revision \x80\n%%EOF')
    assert outcome['state'] == 'failed' and outcome['error_code'] == 'vehicle_pdf_revision_unreviewed'
    assert outcome['receipt']['reaped'] and count(ctx, VehicleSnapshot) == 0
    before = totals(ctx)
    response = history(ctx, capture_id, bundle_id)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['state'] == 'failed' and run['completion']['candidate'] is None
    assert run['completion']['error_code'] == 'vehicle_pdf_revision_unreviewed'
    assert run['completion']['receipt']['reaped'] and run['input']['original_mapping_status'] == 'not_attested'
    assert totals(ctx) == before


def test_selected_mapping_changes_candidate_not_original_snapshot_or_golden_input(private):
    ctx = private
    accepted = adopt(ctx)
    capture_id, first_bundle = original(ctx, accepted)
    first = history(ctx, capture_id, first_bundle).json()
    private_mapping_revision(ctx)
    with ctx.database.sessions() as db:
        second_bundle = parser_releases.current_deployment(db, SOURCE).bundle_id
    second = history(ctx, capture_id, second_bundle).json()
    assert second['state'] == first['state'] == 'completed' and first['input'] == second['input']
    old, new = [item['completion']['candidate']['parse_provenance'] for item in (first, second)]
    assert old['mapping_id'].endswith('@1') and new['mapping_id'].endswith('@2')
    assert old['bundle_id'] != new['bundle_id'] and old['mapping_file_sha256'] != new['mapping_file_sha256']
    assert first['completion']['fingerprint'] != second['completion']['fingerprint']
    with ctx.database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, accepted['provenance'][0]['snapshot_id'])
        assert snapshot.payload['parse_provenance'] == old and snapshot.fact_version == 1
    assert count(ctx, VehicleSnapshot) == 1


@pytest.mark.parametrize('damage', ['object', 'encoding', 'fact', 'verification', 'duplicate'],
                         ids=['object', 'encoding', 'fact-hash', 'verification-pin', 'duplicate-fitment'])
def test_binary_baseline_integrity_blocks_before_history_child(private, monkeypatch, damage):
    ctx = private
    accepted = adopt(ctx)
    capture_id, bundle_id = original(ctx, accepted)
    snapshot_id = accepted['provenance'][0]['snapshot_id']
    if damage in {'object', 'encoding'}:
        damage_snapshot(ctx, snapshot_id, damage)
    else:
        with ctx.database.engine.begin() as connection:
            if damage == 'verification':
                connection.execute(update(VehicleVerification).values(parser_identity={
                    'bundle_id': '0' * 64, 'parser_digest': '1' * 64, 'deployment_revision': 1}))
            elif damage == 'fact':
                connection.execute(update(VehicleSnapshot).values(fact_hash='0' * 64))
            else:
                with ctx.database.sessions() as db:
                    payload = deepcopy(db.get(VehicleSnapshot, snapshot_id).payload)
                payload['fitments'].append(deepcopy(payload['fitments'][0]))
                connection.execute(update(VehicleSnapshot).values(payload=payload, fact_hash=fitment_fact_hash(payload)))
    calls = []
    async def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError('damaged baseline must not execute')
    monkeypatch.setattr(runtime, 'parse_isolated', forbidden)
    response = history(ctx, capture_id, bundle_id)
    assert response.status_code == 503 and response.json()['detail'] == {'code': 'vehicle_raw_integrity_failed'}
    assert calls == [] and count(ctx, ReparseRun) == 0


def test_reserve_then_raw_damage_is_durable_without_child_or_database_fallback(private, monkeypatch):
    ctx = private
    capture_id, bundle_id, _ = seed_raw(ctx, ctx.adapter.load())
    original_reader = reparse.checked_history_capture_bytes
    def damaged(db, capture, **kwargs):
        assert count(ctx, ReparseRun) == 1
        with ctx.database.engine.begin() as connection:
            connection.execute(update(RawCapture).where(RawCapture.id == capture_id).values(
                raw_body=b'!' * capture.byte_count))
        return original_reader(db, capture, **kwargs)
    monkeypatch.setattr(reparse, 'checked_history_capture_bytes', damaged)
    calls = []
    async def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError('corrupt raw must not reach child')
    monkeypatch.setattr(runtime, 'parse_isolated', forbidden)
    response = history(ctx, capture_id, bundle_id)
    assert response.status_code == 503 and not calls
    run = ctx.client.get('/v1/reparse/runs/' + response.json()['detail']['run_id'] + '?mode=history').json()
    assert run['state'] == 'failed' and run['completion']['error_code'] == 'capture_integrity_failed'


@pytest.mark.parametrize('damage', ['receipt', 'provenance', 'budget'], ids=['receipt', 'caller-block', 'final-budget'])
def test_actual_child_receipt_and_server_candidate_provenance_are_not_optional(private, monkeypatch, damage):
    ctx = private
    accepted = adopt(ctx)
    capture_id, bundle_id = original(ctx, accepted)
    actual = runtime.parse_isolated
    async def altered(*args, **kwargs):
        parsed = await actual(*args, **kwargs)
        if damage == 'receipt':
            parsed['receipt']['input_hash'] = '0' * 64
        elif damage == 'provenance':
            parsed['payload']['parse_provenance'] = {}
        return parsed
    monkeypatch.setattr(runtime, 'parse_isolated', altered)
    if damage == 'budget':
        monkeypatch.setattr(reparse, 'MAX_CANDIDATE_BYTES',
                            len(stable_json(ctx.adapter.results[-1]['payload']).encode('utf-8')) + 10)
    response = history(ctx, capture_id, bundle_id)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['state'] == 'failed' and run['completion']['candidate'] is None
    assert run['completion']['receipt']['reaped'] and count(ctx, VehicleSnapshot) == 1


def test_private_binary_golden_release_positive_gate_is_reachable_without_facts(private, monkeypatch):
    ctx = private
    accepted = adopt(ctx)
    capture_id, bundle_id = original(ctx, accepted)
    frozen, _ = golden_set(ctx, capture_id, ctx.adapter.results[-1]['payload'])
    before = totals(ctx)
    observe_child_transactions(ctx, monkeypatch, parser_releases)
    response = evaluate(ctx, capture_id, bundle_id, frozen)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['state'] == 'completed' and result['can_approve'] and result['golden_gate']['state'] == 'passed'
    item = result['completion']['results'][0]
    for arm in ('control', 'candidate'):
        assert item[arm]['parse_provenance']['bundle_id'] == bundle_id
        assert item[arm + '_receipt']['reaped'] and item[arm + '_receipt']['exit_code'] == 0
    approved = approve(ctx, result)
    assert approved.status_code == 201, approved.text
    transitioned = post(ctx.client, f'/v1/parser-deployments/{SOURCE}/transitions', {'action': 'activate',
        'expected_revision': 1, 'target_bundle_id': bundle_id, 'evaluation_id': result['id'],
        'expected_review_revision': 1, **SIGNED})
    assert transitioned.status_code == 201, transitioned.text
    assert totals(ctx) == before


@pytest.mark.parametrize('gate', ['missing', 'mismatch', 'revoked'], ids=['missing', 'mismatch', 'revoked'])
def test_binary_golden_required_gate_cannot_be_acknowledged_away(private, gate):
    ctx = private
    accepted = adopt(ctx)
    capture_id, bundle_id = original(ctx, accepted)
    frozen, case = (None, None) if gate == 'missing' else golden_set(ctx, capture_id,
        ctx.adapter.results[-1]['payload'], mismatch=gate == 'mismatch')
    response = evaluate(ctx, capture_id, bundle_id, frozen)
    assert response.status_code == 201, response.text
    result = response.json()
    if gate == 'revoked':
        sign_case(ctx.client, case, 'revoke')
    assert approve(ctx, result, acknowledge_reference_gaps=True).status_code == 409
    assert count(ctx, VehicleSnapshot) == 1


def test_old_control_with_mapping_file_is_real_failure_even_with_accepted_reference_and_golden(private):
    ctx = private
    accepted = adopt(ctx)
    capture_id, target_bundle = original(ctx, accepted)
    frozen, _ = golden_set(ctx, capture_id, ctx.adapter.results[-1]['payload'])
    path = ctx.source / 'adapters/xiaomi.py'
    source = path.read_bytes()
    assert source.count(b'xiaomi-param-comparison@1.1.0') == 1
    path.write_bytes(source.replace(b'xiaomi-param-comparison@1.1.0', b'xiaomi-param-comparison@1.0.1'))
    with ctx.database.sessions() as db:
        old_id = parser_releases.register_deployed_bundle(db, 'Private R90', 'Synthetic old control')['id']
        bundle = db.get(ParserBundle, old_id)
        db.add(ParserDeploymentRevision(source_id=SOURCE, revision=2, state='active', bundle_id=old_id,
            descriptor=deepcopy(bundle.descriptors[SOURCE]), action='bootstrap', actor_session_id=ctx.session_id,
            idempotency_key=str(uuid4()), request_hash=digest('private-r90-old-control'),
            operator='Private R90', reason='Synthetic old control, no release qualification'))
        db.commit()
    response = evaluate(ctx, capture_id, target_bundle, frozen)
    assert response.status_code == 201, response.text
    result = response.json()
    item = result['completion']['results'][0]
    assert item['reference_kind'] == 'accepted_same_raw' and item['candidate'] is not None
    assert item['control'] is None and item['control_error'] and item['control_receipt']['reaped']
    assert item['candidate_receipt']['reaped'] and item['candidate']['parse_provenance']['bundle_id'] == target_bundle
    assert item['control_capability_gap'] == item['control_error']
    assert any(block['code'] == 'binary_control_failed' for block in result['completion']['hard_blocks'])
    assert result['state'] == 'failed' and not result['can_approve']
    assert approve(ctx, result, acknowledge_reference_gaps=True).status_code == 409
    assert count(ctx, VehicleSnapshot) == 1


# Derived only from the exact pre-R90 hash key sets and canonical JSON contract.
LEGACY_VECTORS = json.loads(r'''{
  "run": {
    "id": "legacy-run",
    "input": {
      "capture_id": "legacy-capture",
      "query_id": "legacy-query",
      "source_id": "xiaomi-cn-vehicles",
      "target_kind": "vehicle",
      "query": {
        "vehicle_id": "xiaomi-su7-current"
      },
      "query_key": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "source_url": "https://example.invalid/legacy-json",
      "content_type": "application/json",
      "raw_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "byte_count": 20,
      "observed_at": "2026-01-01T00:00:00+00:00",
      "storage_kind": "database_legacy",
      "original_parser_version": "legacy@1",
      "original_parser_identity": null
    },
    "parser": {
      "version": "legacy@1",
      "digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    },
    "baseline": {
      "snapshot_id": "legacy-snapshot",
      "verification_id": "legacy-verification",
      "verified_at": "2026-01-01T00:00:01+00:00",
      "observed_at": "2026-01-01T00:00:00+00:00",
      "raw_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "source_url": "https://example.invalid/legacy-json",
      "parser_version": "legacy@1",
      "parser_identity": null,
      "selected_at": "2026-01-01T00:00:02+00:00",
      "payload": {
        "vehicle": {
          "id": "xiaomi-su7-current"
        },
        "trims": [],
        "fitments": []
      }
    },
    "input_hash": "9b57492a273d7b4c9714d52440d43b13d3d0472958221ba525615cdd6fd177d5"
  },
  "payload": {
    "vehicle": {
      "id": "xiaomi-su7-current"
    },
    "trims": [],
    "fitments": []
  },
  "quality": {
    "reason_codes": []
  },
  "diff": {
    "total_changed_fields": 0
  },
  "receipt": {
    "run_id": "dddddddddddddddddddddddddddddddd"
  },
  "completion": "535065d4e0120d1d9d3063d5745dafa7ab75cc58841570a6a628c685e31380f0",
  "evaluation": {
    "id": "legacy-evaluation",
    "source_id": "xiaomi-cn-vehicles",
    "target_bundle_id": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "control_bundle_id": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "deployment_revision": 1,
    "bindings": [
      {
        "input": {
          "capture_id": "legacy-capture",
          "query_id": "legacy-query",
          "source_id": "xiaomi-cn-vehicles",
          "target_kind": "vehicle",
          "query": {
            "vehicle_id": "xiaomi-su7-current"
          },
          "query_key": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "source_url": "https://example.invalid/legacy-json",
          "content_type": "application/json",
          "raw_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "byte_count": 20,
          "observed_at": "2026-01-01T00:00:00+00:00",
          "storage_kind": "database_legacy",
          "original_parser_version": "legacy@1",
          "original_parser_identity": null
        },
        "reference": {
          "snapshot_id": "legacy-snapshot",
          "verification_id": "legacy-verification",
          "verified_at": "2026-01-01T00:00:01+00:00",
          "observed_at": "2026-01-01T00:00:00+00:00",
          "raw_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "source_url": "https://example.invalid/legacy-json",
          "parser_version": "legacy@1",
          "parser_identity": null,
          "selected_at": "2026-01-01T00:00:02+00:00",
          "payload": {
            "vehicle": {
              "id": "xiaomi-su7-current"
            },
            "trims": [],
            "fitments": []
          }
        }
      }
    ],
    "input_hash": "9b3b497fba7a90627af5ec239f8496c5bcc5a4bb2405d3839a9da0867407f96c"
  },
  "results": [
    {
      "capture_id": "legacy-capture",
      "candidate": {
        "vehicle": {
          "id": "xiaomi-su7-current"
        },
        "trims": [],
        "fitments": []
      },
      "control": {
        "vehicle": {
          "id": "xiaomi-su7-current"
        },
        "trims": [],
        "fitments": []
      }
    }
  ],
  "evaluation_completion": "416f326454c5547f5a61d6a6a0b13a76074f6bb941dffd868428e9dc75b8be2b",
  "case": {
    "id": "legacy-case",
    "kind": "vehicle",
    "source_id": "xiaomi-cn-vehicles"
  },
  "content": {
    "revision": 1,
    "title": "旧文本冻结向量",
    "capture_id": "legacy-capture",
    "input": {
      "capture_id": "legacy-capture",
      "query_id": "legacy-query",
      "source_id": "xiaomi-cn-vehicles",
      "target_kind": "vehicle",
      "query": {
        "vehicle_id": "xiaomi-su7-current"
      },
      "query_key": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "source_url": "https://example.invalid/legacy-json",
      "content_type": "application/json",
      "raw_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "byte_count": 20,
      "observed_at": "2026-01-01T00:00:00+00:00",
      "storage_kind": "database_legacy",
      "original_parser_version": "legacy@1",
      "original_parser_identity": null
    },
    "evidence_note": "Frozen algorithm vector, not a before-run receipt",
    "expected": {
      "vehicle": {
        "id": "xiaomi-su7-current"
      },
      "trims": [],
      "fitments": []
    },
    "previous_fingerprint": null,
    "operator": "Synthetic",
    "reason": "Legacy serialization contract"
  },
  "content_hash": "9da1906368155bf1c1716a1f8b276d1d2f6d33dd019f5bec13c1b70ddeccbd7b",
  "review": {
    "case_id": "legacy-case",
    "case_revision": 1,
    "case_fingerprint": "9da1906368155bf1c1716a1f8b276d1d2f6d33dd019f5bec13c1b70ddeccbd7b",
    "revision": 1,
    "action": "approve",
    "previous_fingerprint": null,
    "operator": "Synthetic",
    "reason": "Frozen review vector"
  },
  "review_hash": "dff2abcd908ad1da9bb52efb05b9b0c79402ae4b6f9ea9334c14b4da30d60cbe",
  "set": {
    "set_id": "legacy-set",
    "revision": 1,
    "action": "freeze",
    "title": "Legacy set",
    "source_id": "xiaomi-cn-vehicles",
    "kind": "vehicle",
    "cases": [],
    "previous_fingerprint": null,
    "operator": "Synthetic",
    "reason": "Frozen set vector"
  },
  "set_hash": "c11a9edaf70da045b550d317c8c0919a9226270831e8e364f2a584cfc5e3a079"
}''')


def test_legacy_utf8_frozen_input_completion_golden_and_release_hash_vectors():
    vector = LEGACY_VECTORS
    run = SimpleNamespace(**vector['run'])
    assert not {'body_encoding', 'original_mapping_status'} & run.input.keys()
    assert digest({'input': run.input, 'parser': run.parser, 'baseline': run.baseline}) == run.input_hash
    assert reparse.completion_binding(run, 'completed', None, vector['payload'], vector['quality'],
        vector['diff'], vector['receipt']) == vector['completion']
    evaluation = SimpleNamespace(**vector['evaluation'])
    assert digest(parser_releases._evaluation_input(evaluation)) == evaluation.input_hash
    assert parser_releases._completion_hash(evaluation, 'completed', vector['results'], [], []) == vector['evaluation_completion']
    assert golden._content_hash(SimpleNamespace(**vector['case']), SimpleNamespace(**vector['content'])) == vector['content_hash']
    assert golden._review_hash(SimpleNamespace(**vector['review'])) == vector['review_hash']
    assert golden._set_hash(SimpleNamespace(**vector['set'])) == vector['set_hash']


def test_missing_frozen_binary_capture_is_a_fixed_503_before_object_access(private):
    from fastapi import HTTPException
    with private.database.sessions() as db:
        with pytest.raises(HTTPException) as raised:
            reparse.checked_history_capture_bytes(db, None,
                frozen_input={'capture_id': 'missing-r90-private-capture', 'body_encoding': 'binary'})
        assert raised.value.status_code == 503 and raised.value.detail == {'code': 'capture_integrity_failed'}


def test_missing_exact_release_verification_never_falls_back(monkeypatch):
    from tire_api import vehicle_raw
    capture = SimpleNamespace(target_kind='vehicle', query_id='exact-query',
        source_id=SOURCE, raw_hash='0' * 64)
    snapshot = SimpleNamespace(id='exact-snapshot', body_encoding='binary',
        source_id=SOURCE, vehicle_id=VEHICLE)
    results = iter([snapshot, None])
    calls = []
    def scalar(statement):
        calls.append(statement)
        return next(results)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('missing exact verification must not seek another query')
    monkeypatch.setattr(vehicle_raw, 'checked_vehicle_history_baseline', forbidden)
    with pytest.raises(parser_releases.ParserDeploymentError) as raised:
        parser_releases._reference_snapshot(SimpleNamespace(scalar=scalar), capture)
    assert raised.value.status_code == 503 and raised.value.code == 'vehicle_raw_integrity_failed'
    assert len(calls) == 2
