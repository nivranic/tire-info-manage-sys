"""Explicit two-account review of supplied material, never automatic SKU inference."""
from copy import deepcopy
import hashlib
from typing import Literal
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request, Response
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from sqlalchemy import desc, func, select

from .auth import current_user, make_admin_guard
from .db import EvidenceDocument, EvidenceObject, FactVersion, Snapshot, VariantLifecycleEvent, uid, utcnow
from .documents import document_metadata
from .domain import StrictModel, digest
from .identity_contract import contract_context, contract_metadata, IdentityContractError
from .identity_models import IdentityRevision
from .interest_events import _catalog_memberships, _tire_side
from .object_store import ObjectStoreError
from .service import QueryService, provenance, timestamp
from .test_events import EventPayload, TireTestRevision, latest as latest_event
from .test_sku_link_models import TestSkuLink, TestSkuLinkRevision

SCHEMA = 'test-sku-link@1'
POLICY_VERSION = 'supplied-test-sku-link@1'
BOUNDARY = {'material_origin': 'operator_supplied', 'origin_verification': 'unverified',
    'read_scope': 'local_workspace', 'test_record_kind': 'manual_transcription',
    'test_verification': 'unverified', 'provider_use': False, 'export': False,
    'notice': '操作者提供的共享材料与人工转录，未经来源在线核验；双账户不证明两个真人独立。材料位置与引文为人工声明，不是PDF语义抽取或独立认证；本关联不代表适配、性能推荐或跨场排名。'}
IdentityField = Literal['brand', 'model', 'manufacturer_product_code', 'region', 'size', 'load_index',
    'speed_rating', 'xl', 'hl', 'oe_mark', 'acoustic_technology', 'run_flat', 'product_code_type',
    'gtin', 'technology_features', 'eprel_id']
Action = Literal['create', 'revise', 'review', 'revoke', 'restore']
EvidenceLevel = Literal['manual_assertion', 'source_explicit_identifiers_in_supplied_material']


class Closed(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)

    @field_validator('*')
    @classmethod
    def bounded_original_text(cls, value):
        if isinstance(value, str):
            try:
                value.encode('utf-8', errors='strict')
            except UnicodeError:
                raise ValueError('文字必须是合法UTF-8') from None
            if not value.strip() or any(ord(c) < 32 and c not in '\n\t' for c in value):
                raise ValueError('文字不得为空白或包含控制字符')
        return value


class BridgeSelection(Closed):
    event_id: str = Field(min_length=1, max_length=64)
    event_revision_id: str = Field(min_length=1, max_length=64)
    participant_key: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    variant_id: str = Field(min_length=1, max_length=64)
    tire_snapshot_id: str = Field(min_length=1, max_length=64)
    fact_version_id: str = Field(min_length=1, max_length=64)


class BridgeLocator(Closed):
    page: StrictInt = Field(ge=1, le=100000)
    region: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=300)


class BridgeRights(Closed):
    rights_holder: str = Field(min_length=1, max_length=160)
    basis: str = Field(min_length=1, max_length=1000)
    store_original: StrictBool
    workspace_reopen: StrictBool
    quote_identifiers: StrictBool

    @field_validator('store_original', 'workspace_reopen', 'quote_identifiers')
    @classmethod
    def explicit_rights(cls, value):
        if value is not True:
            raise ValueError('必须明确声明保存、共享重开及标识短引文权限')
        return value


class BridgeMaterial(Closed):
    document_id: str = Field(min_length=1, max_length=64)
    expected_raw_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_metadata_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    event_locator: BridgeLocator
    participant_locator: BridgeLocator
    rights: BridgeRights


class BridgeAssertion(BridgeLocator):
    field: IdentityField
    material_document_id: str = Field(min_length=1, max_length=64)
    material_value: StrictStr | StrictBool


class OpenedMaterial(Closed):
    document_id: str = Field(min_length=1, max_length=64)
    raw_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    metadata_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


class BridgePreviewRequest(Closed):
    mode: Literal['history']
    action: Action
    link_id: str | None = Field(default=None, min_length=1, max_length=64)
    selection: BridgeSelection
    materials: list[BridgeMaterial] = Field(max_length=3)
    assertions: list[BridgeAssertion] = Field(max_length=20)
    evidence_level: EvidenceLevel

    @model_validator(mode='after')
    def unique_references(self):
        if (self.action == 'create') != (self.link_id is None):
            raise ValueError('创建不得指定已有关系，其他操作必须指定关系')
        if len({m.document_id for m in self.materials}) != len(self.materials):
            raise ValueError('材料引用不能重复')
        if len({a.field for a in self.assertions}) != len(self.assertions):
            raise ValueError('每个身份字段只能声明一次')
        return self


class BridgeDecision(BridgePreviewRequest):
    expected_revision: StrictInt = Field(ge=0)
    expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    declaration_revision_id: str | None = Field(min_length=1, max_length=64)
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=5, max_length=2000)
    acknowledged: StrictBool
    opened_materials: list[OpenedMaterial] = Field(max_length=3)
    confirmed_event_revision_id: str = Field(min_length=1, max_length=64)
    confirmed_participant_hash: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('acknowledged')
    @classmethod
    def acknowledged_boundary(cls, value):
        if value is not True:
            raise ValueError('必须明确确认未核验人工材料边界')
        return value


def fail(code, message='证据或状态不符合本地人工关联合同，请重新核对。', status=409):
    raise HTTPException(status, {'code': code, 'message': message}, headers={'Cache-Control': 'no-store'})


def quote_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def reconstruct_event_participant(db, selected, *, allow_missing=False):
    row = db.get(TireTestRevision, selected.event_revision_id)
    if row is None or row.event_id != selected.event_id:
        fail('test_sku_event_scope_mismatch', status=422)
    try:
        valid = EventPayload.model_validate(row.payload).model_dump(mode='json') == row.payload
    except (ValueError, TypeError):
        valid = False
    participants = [p for p in row.payload.get('participants', []) if p.get('key') == selected.participant_key]
    if (not valid or digest(row.payload) != row.fingerprint or len(participants) > 1
            or not participants and not allow_missing
            or row.state not in ('active', 'revoked')):
        fail('test_sku_event_evidence_invalid', status=422)
    return {'event_id': row.event_id, 'revision_id': row.id, 'revision': row.revision,
        'state': row.state, 'fingerprint': row.fingerprint, 'event': deepcopy(row.payload),
        'participant': deepcopy(participants[0]) if participants else None,
        'participant_hash': digest(participants[0]) if participants else None,
        'participant_present': bool(participants)}


def reconstruct_tire_evidence(db, selected, asof=None):
    fact = db.get(FactVersion, selected.fact_version_id)
    side, _refs = _tire_side(db, selected.tire_snapshot_id, selected.variant_id, fact, asof or utcnow())
    if not side['evidence_valid']:
        fail('test_sku_tire_evidence_invalid', status=422)
    snapshot = db.get(Snapshot, selected.tire_snapshot_id)
    members = [m for m in snapshot.parsed_variants if m.get('id') == selected.variant_id]
    return {**{key: deepcopy(side[key]) for key in ('snapshot_id', 'identity', 'identity_key', 'identity_status',
        'identity_contract_version', 'facts', 'fact_version_id', 'fact_version', 'facts_hash', 'structured_locator')},
        'variant_id': selected.variant_id, 'source_id': snapshot.source_id, 'query_key': snapshot.query_key,
        'raw_hash': snapshot.raw_hash, 'snapshot_member': deepcopy(members[0]),
        'parsed_variants_hash': digest(snapshot.parsed_variants), 'provenance': provenance(snapshot)}


def material_metadata(db, document_id):
    row = db.get(EvidenceDocument, document_id)
    blob = db.get(EvidenceObject, row.raw_hash) if row else None
    if (row is None or blob is None or row.content_type != 'application/pdf'
            or type(blob.byte_count) is not int or not 1 <= blob.byte_count <= 8 * 1024 * 1024):
        fail('test_sku_material_metadata_invalid', status=422)
    metadata = document_metadata(row, blob.byte_count)
    return row, blob, metadata, digest({**metadata, 'actor_session_id': row.actor_session_id})


def freeze_materials(db, materials):
    result = []
    for material in materials:
        row, blob, metadata, metadata_hash = material_metadata(db, material.document_id)
        if material.expected_raw_hash != row.raw_hash or material.expected_metadata_hash != metadata_hash:
            fail('test_sku_material_changed', status=422)
        try:
            body = db.info['object_store'].get(row.raw_hash, blob.byte_count)
            if (len(body) != blob.byte_count or quote_hash_bytes(body) != row.raw_hash or not body.startswith(b'%PDF-')):
                raise ObjectStoreError('material_integrity_failed')
        except (ObjectStoreError, OSError, KeyError, TypeError):
            fail('test_sku_material_integrity_failed', status=422)
        entry = material.model_dump()
        entry.pop('expected_raw_hash')
        entry.pop('expected_metadata_hash')
        for key in ('event_locator', 'participant_locator'):
            entry[key]['quote_sha256'] = quote_hash(entry[key]['quote'])
        result.append({**entry, 'metadata': metadata, 'raw_hash': row.raw_hash, 'metadata_hash': metadata_hash,
            'material_origin': 'operator_supplied', 'origin_verification': 'unverified', 'read_scope': 'local_workspace'})
    return result


def quote_hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def validate_assertions(assertions, identity, materials):
    by_field = {a.field: a for a in assertions}
    document_ids = {m['document_id'] for m in materials}
    if any(a.material_document_id not in document_ids or a.field not in identity for a in assertions):
        fail('test_sku_assertion_scope_invalid', status=422)
    checks = []
    for field, expected in identity.items():
        assertion = by_field.get(field)
        value = assertion.material_value if assertion else None
        status = ('unsupported' if expected is not None and type(expected) not in (str, bool) else 'unknown' if expected is None or assertion is None
                  else 'match' if type(value) is type(expected) and value == expected else 'conflict')
        checks.append({'field': field, 'status': status, 'material_value': value, 'sku_value': deepcopy(expected)})
    frozen = [{**a.model_dump(), 'quote_sha256': quote_hash(a.quote)} for a in assertions]
    return frozen, checks


def cross_side_checks(test, tire):
    pairs = [('test_size_scope', test['event']['tested_size'], tire['identity'].get('size')),
        ('test_participant_brand', test['participant']['brand'], tire['identity'].get('brand')),
        ('test_participant_model', test['participant']['model'], tire['identity'].get('model'))]
    return [{'field': field, 'status': 'match' if type(value) is type(expected) and value == expected else 'conflict',
             'material_value': value, 'sku_value': expected} for field, value, expected in pairs]


def current_link_binding(db, selected):
    current = latest_event(db, selected.event_id)
    event_selected = selected.model_copy(update={'event_revision_id': current.id})
    test = reconstruct_event_participant(db, event_selected, allow_missing=True)
    try:
        context = contract_context(db, [selected.variant_id])
        contract = (contract_metadata(db, selected.variant_id, context=context) if selected.variant_id in context['variants']
                    else {'schema': None, 'state': 'missing', 'current_identity': None,
                          'identity_status': None, 'current_key': None})
    except IdentityContractError as error:
        fail(error.code, status=error.status_code)
    bound = context['bindings'].get(selected.variant_id)
    identity = db.scalar(select(IdentityRevision).where(IdentityRevision.variant_id == selected.variant_id)
                         .order_by(desc(IdentityRevision.revision)).limit(1))
    if identity and digest(identity.binding) != identity.binding_hash:
        fail('test_sku_identity_decision_invalid', status=422)
    lifecycle = db.scalar(select(VariantLifecycleEvent).where(VariantLifecycleEvent.variant_id == selected.variant_id)
                          .order_by(desc(VariantLifecycleEvent.revision)).limit(1))
    catalogs = _catalog_memberships(db, selected.variant_id, utcnow())
    if catalogs is None:
        fail('test_sku_catalog_evidence_invalid', status=422)
    return {'policy_version': POLICY_VERSION,
        'test': {key: test[key] for key in ('event_id', 'revision_id', 'revision', 'state', 'fingerprint', 'participant_hash', 'participant_present')},
        'identity_contract': {'schema': contract['schema'], 'state': contract['state'],
            'binding_id': bound.id if bound else None, 'binding_fingerprint': bound.fingerprint if bound else None,
            'identity': deepcopy(contract['current_identity']), 'identity_status': contract['identity_status'],
            'current_key': contract['current_key']},
        'identity_resolution': {'id': identity.id if identity else None, 'revision': identity.revision if identity else 0,
            'state': 'cleared' if identity and identity.action == 'clear' else 'blocked' if identity else 'independent'},
        'lifecycle': {'id': lifecycle.id if lifecycle else None, 'revision': lifecycle.revision if lifecycle else 0,
            'state': lifecycle.after_state if lifecycle else 'active'}, 'catalogs': catalogs}


SIGNED_FIELDS = ('id', 'link_id', 'revision', 'action', 'review_state', 'declaration_revision_id',
    'declared_by_user_id', 'selection', 'materials', 'evidence_level', 'frozen_evidence', 'material_evidence',
    'assertions', 'checks', 'binding', 'binding_hash', 'before', 'after', 'attestation', 'operator', 'reason',
    'actor_user_id', 'actor_session_id', 'idempotency_key', 'request_hash')


def revision_fingerprint(row):
    return digest({**{key: getattr(row, key) for key in SIGNED_FIELDS}, 'created_at': timestamp(row.created_at)})


def checked_revision(row):
    if row is None:
        fail('test_sku_link_missing', status=404)
    if row.fingerprint != revision_fingerprint(row) or row.binding_hash != digest(row.binding):
        fail('test_sku_link_revision_integrity_failed', status=422)
    return row


def latest_revision(db, link_id):
    return checked_revision(db.scalar(select(TestSkuLinkRevision).where(TestSkuLinkRevision.link_id == link_id)
        .order_by(desc(TestSkuLinkRevision.revision)).limit(1)))


def reconstruct_link_revision(db, row):
    checked_revision(row)
    try:
        selected = BridgeSelection.model_validate(row.selection)
        materials = [BridgeMaterial.model_validate(m) for m in row.materials]
        assertions = [BridgeAssertion.model_validate({key: value for key, value in a.items() if key != 'quote_sha256'})
                      for a in row.assertions]
        test = reconstruct_event_participant(db, selected)
        tire = reconstruct_tire_evidence(db, selected, row.created_at)
        material_evidence = freeze_materials(db, materials)
        frozen_assertions, checks = validate_assertions(assertions, tire['identity'], material_evidence)
        checks += cross_side_checks(test, tire)
    except (ValueError, TypeError, KeyError, AttributeError):
        fail('test_sku_link_revision_integrity_failed', status=422)
    link = db.get(TestSkuLink, row.link_id)
    if (link is None or (link.event_id, link.participant_key) != (selected.event_id, selected.participant_key)
            or digest(row.frozen_evidence) != digest({'test': test, 'tire': tire})
            or digest(material_evidence) != digest(row.material_evidence)
            or digest(frozen_assertions) != digest(row.assertions) or digest(checks) != digest(row.checks)):
        fail('test_sku_link_frozen_evidence_invalid', status=422)
    declaration = checked_revision(db.get(TestSkuLinkRevision, row.declaration_revision_id))
    if (declaration.link_id != row.link_id or declaration.action not in ('create', 'revise')
            or declaration.id != declaration.declaration_revision_id
            or declaration.actor_user_id != row.declared_by_user_id
            or any(digest(getattr(row, key)) != digest(getattr(declaration, key)) for key in
                   ('selection', 'materials', 'evidence_level', 'frozen_evidence', 'material_evidence', 'assertions', 'checks'))):
        fail('test_sku_declaration_integrity_failed', status=422)
    if row.action == 'review' and row.actor_user_id == row.declared_by_user_id:
        fail('test_sku_self_review', status=422)
    return selected


def assess_link(frozen, binding, *, prior_binding=None, review_state='pending_review', evidence_level='manual_assertion',
                checks=(), reviewed_by=None, declared_by=None):
    blockers, stale = [], []
    test, tire = frozen['test'], frozen['tire']
    if binding['test']['revision_id'] != test['revision_id'] or binding['test']['participant_hash'] != test['participant_hash']:
        blockers.append('test_event_revision_changed')
    if not binding['test']['participant_present']:
        blockers.append('test_participant_missing')
    if binding['test']['state'] != 'active':
        blockers.append('test_event_revoked')
    contract = binding['identity_contract']
    if contract['state'] != 'current' or contract['identity'] != tire['identity']:
        blockers.append('tire_identity_contract_changed')
    if binding['identity_resolution']['state'] == 'blocked':
        blockers.append('tire_identity_review_required')
    if binding['lifecycle']['state'] != 'active':
        blockers.append('tire_lifecycle_revoked')
    if not binding['catalogs'] or any(not item['present'] for item in binding['catalogs']):
        blockers.append('tire_catalog_membership_changed')
    if evidence_level == 'source_explicit_identifiers_in_supplied_material':
        if any(c['status'] == 'conflict' and not c['field'].startswith('test_') for c in checks):
            blockers.append('material_identity_conflict')
        blockers.extend(c['field'] + '_mismatch' for c in checks if c['status'] == 'conflict' and c['field'].startswith('test_'))
        if any(c['status'] in ('unknown', 'unsupported') for c in checks):
            blockers.append('identity_assertions_incomplete')
        if contract['identity_status'] != 'complete':
            blockers.append('complete_identity_required')
        if test['event']['tested_size'] != tire['identity'].get('size'):
            blockers.append('test_size_scope_mismatch')
    if prior_binding is not None:
        stale = [key + '_changed' for key in binding if digest(prior_binding.get(key)) != digest(binding[key])]
    effective = 'revoked' if review_state == 'revoked' else 'needs_review' if stale or blockers else review_state
    eligible = (review_state == 'reviewed' and not stale and not blockers and reviewed_by != declared_by
                and reviewed_by is not None and evidence_level == 'source_explicit_identifiers_in_supplied_material')
    return {'effective_state': effective, 'eligibility': 'conditional_reviewed_transcription' if eligible else 'none',
            'blockers': blockers, 'stale_reasons': stale}


def declaration_values(payload):
    return {'selection': payload.selection.model_dump(), 'materials': [m.model_dump() for m in payload.materials],
            'assertions': [a.model_dump() for a in payload.assertions], 'evidence_level': payload.evidence_level}


def public_assertions(row):
    return [{key: value for key, value in a.items() if key != 'quote_sha256'} for a in row.assertions]


def event_summary(row):
    return {key: deepcopy(getattr(row, key)) for key in ('revision', 'action', 'review_state',
        'declaration_revision_id', 'declared_by_user_id', 'actor_user_id', 'operator', 'reason', 'fingerprint')} | {
        'revision_id': row.id, 'created_at': timestamp(row.created_at)}


def allowed_actions(row, actor):
    if not actor or not actor.is_admin:
        return []
    if row is None:
        return ['create']
    if row.review_state == 'revoked':
        return ['restore']
    return ['revise', 'revoke'] + (['review'] if actor.id != row.declared_by_user_id else [])


def preview_link(db, payload, actor):
    previous = latest_revision(db, payload.link_id) if payload.link_id else None
    if previous:
        reconstruct_link_revision(db, previous)
    test = reconstruct_event_participant(db, payload.selection)
    tire = reconstruct_tire_evidence(db, payload.selection)
    material_evidence = freeze_materials(db, payload.materials)
    assertions, checks = validate_assertions(payload.assertions, tire['identity'], material_evidence)
    checks += cross_side_checks(test, tire)
    frozen = {'test': test, 'tire': tire}
    binding = current_link_binding(db, payload.selection)
    assessment = assess_link(frozen, binding, checks=checks, evidence_level=payload.evidence_level)
    blockers = assessment['blockers']
    if payload.evidence_level != 'manual_assertion':
        if not material_evidence:
            blockers.append('explicit_identifiers_require_material')
        if any(m['metadata']['source_url'] != test['event']['source_url'] for m in material_evidence):
            blockers.append('material_event_source_scope_mismatch')
    if previous:
        link = db.get(TestSkuLink, previous.link_id)
        if (link.event_id, link.participant_key) != (payload.selection.event_id, payload.selection.participant_key):
            blockers.append('fixed_link_scope_mismatch')
        if payload.action in ('review', 'revoke', 'restore') and declaration_values(payload) != {
                'selection': previous.selection, 'materials': previous.materials,
                'assertions': public_assertions(previous), 'evidence_level': previous.evidence_level}:
            blockers.append('revise_required_for_changed_declaration')
        if payload.action == 'review' and actor.id == previous.declared_by_user_id:
            blockers.append('test_sku_self_review')
        if previous.review_state == 'revoked' and payload.action != 'restore':
            blockers.append('restore_required')
        if payload.action == 'restore' and previous.review_state != 'revoked':
            blockers.append('link_not_revoked')
    elif db.scalar(select(TestSkuLink.id).where(TestSkuLink.event_id == payload.selection.event_id,
                                               TestSkuLink.participant_key == payload.selection.participant_key)):
        blockers.append('test_sku_link_scope_exists')
    # Withdrawing stale evidence does not rebind it to today's eligibility.
    if payload.action == 'revoke':
        blockers = [b for b in blockers if b in ('fixed_link_scope_mismatch', 'revise_required_for_changed_declaration', 'restore_required')]
    revision = previous.revision if previous else 0
    basis = {'request': BridgePreviewRequest.model_validate({key: getattr(payload, key) for key in
        BridgePreviewRequest.model_fields}).model_dump(), 'revision': revision,
        'previous_fingerprint': previous.fingerprint if previous else None, 'frozen_evidence': frozen,
        'material_evidence': material_evidence, 'assertions': assertions, 'binding': binding, 'actor_user_id': actor.id}
    return {'schema': SCHEMA, 'scope': 'local_workspace', 'data_state': 'local_snapshot',
        'id': payload.link_id, 'revision': revision, 'revision_id': previous.id if previous else None,
        'review_state': previous.review_state if previous else None, 'effective_state': assessment['effective_state'],
        'eligibility': 'none', 'boundary': deepcopy(BOUNDARY), **declaration_values(payload),
        'frozen_evidence': frozen, 'material_evidence': material_evidence, 'assertions': assertions,
        'checks': checks, 'required_identity_fields': list(tire['identity']),
        'unknown_fields': [c['field'] for c in checks if c['status'] in ('unknown', 'unsupported')],
        'blockers': list(dict.fromkeys(blockers)), 'stale_reasons': [], 'binding': binding, 'binding_hash': digest(binding),
        'fingerprint': digest(basis), 'can_submit': not blockers,
        'confirmed_event_revision_id': test['revision_id'], 'confirmed_participant_hash': test['participant_hash'],
        'declared_by_user_id': previous.declared_by_user_id if previous else None,
        'declaration_revision_id': previous.declaration_revision_id if previous else None,
        'allowed_actions': allowed_actions(previous, actor)}


def link_view(db, row, actor=None, *, history=False):
    selected = reconstruct_link_revision(db, row)
    binding = current_link_binding(db, selected)
    assessment = assess_link(row.frozen_evidence, binding, prior_binding=row.binding,
        review_state=row.review_state, evidence_level=row.evidence_level, checks=row.checks,
        reviewed_by=row.actor_user_id if row.action == 'review' else None, declared_by=row.declared_by_user_id)
    if row.evidence_level != 'manual_assertion' and (not row.material_evidence or any(
            m['metadata']['source_url'] != row.frozen_evidence['test']['event']['source_url'] for m in row.material_evidence)):
        assessment['blockers'].append('material_event_source_scope_mismatch')
        assessment['eligibility'] = 'none'
    latest = latest_revision(db, row.link_id)
    result = {'schema': SCHEMA, 'scope': 'local_workspace', 'data_state': 'local_snapshot', 'id': row.link_id,
        'revision_id': row.id, 'revision': row.revision, 'review_state': row.review_state, **assessment,
        'boundary': deepcopy(BOUNDARY), 'selection': deepcopy(row.selection), 'materials': deepcopy(row.materials),
        'evidence_level': row.evidence_level, 'frozen_evidence': deepcopy(row.frozen_evidence),
        'material_evidence': deepcopy(row.material_evidence), 'assertions': deepcopy(row.assertions),
        'checks': deepcopy(row.checks), 'required_identity_fields': list(row.frozen_evidence['tire']['identity']),
        'unknown_fields': [c['field'] for c in row.checks if c['status'] in ('unknown', 'unsupported')],
        'binding_hash': row.binding_hash, 'fingerprint': row.fingerprint,
        'declared_by_user_id': row.declared_by_user_id, 'declaration_revision_id': row.declaration_revision_id,
        'confirmed_event_revision_id': row.frozen_evidence['test']['revision_id'],
        'confirmed_participant_hash': row.frozen_evidence['test']['participant_hash'],
        'allowed_actions': allowed_actions(row, actor) if latest.id == row.id else []}
    if history:
        rows = db.scalars(select(TestSkuLinkRevision).where(TestSkuLinkRevision.link_id == row.link_id)
                         .order_by(desc(TestSkuLinkRevision.revision)).limit(101)).all()
        result['history'] = [event_summary(checked_revision(item)) for item in rows[:100]]
        result['history_truncated'] = len(rows) > 100
    return result


def append_link_revision(db, payload, session_id, idempotency_key):
    try:
        key = str(UUID(idempotency_key))
    except (ValueError, TypeError, AttributeError):
        fail('invalid_idempotency_key', status=422)
    shared = QueryService(db, None)
    shared.lock_ingestion()
    actor = current_user(db, session_id)
    if actor is None or not actor.is_admin:
        fail('admin_required', status=403)
    request_hash = digest(payload.model_dump())
    replay = db.scalar(select(TestSkuLinkRevision).where(TestSkuLinkRevision.actor_user_id == actor.id,
                                                       TestSkuLinkRevision.idempotency_key == key))
    if replay:
        if replay.request_hash != request_hash:
            fail('idempotency_payload_mismatch')
        result = {'link': link_view(db, replay, actor, history=True), 'event': event_summary(replay), 'idempotent_replay': True}
        db.commit()
        return result
    proposed = preview_link(db, payload, actor)
    if proposed['revision'] != payload.expected_revision or proposed['fingerprint'] != payload.expected_fingerprint:
        fail('test_sku_link_revision_conflict')
    if proposed['declaration_revision_id'] != payload.declaration_revision_id:
        fail('test_sku_declaration_revision_conflict')
    if not proposed['can_submit']:
        fail('test_sku_link_gate_failed', ', '.join(proposed['blockers']))
    if (payload.confirmed_event_revision_id != proposed['confirmed_event_revision_id']
            or payload.confirmed_participant_hash != proposed['confirmed_participant_hash']):
        fail('test_sku_subject_confirmation_mismatch', status=422)
    expected_opened = [{'document_id': m['document_id'], 'raw_hash': m['raw_hash'], 'metadata_hash': m['metadata_hash']}
                       for m in proposed['material_evidence']]
    if payload.action == 'review' and sorted((m.model_dump() for m in payload.opened_materials), key=lambda m: m['document_id']) != sorted(expected_opened, key=lambda m: m['document_id']):
        fail('test_sku_material_open_confirmation_required', status=422)
    previous = latest_revision(db, payload.link_id) if payload.link_id else None
    if previous:
        link = db.get(TestSkuLink, payload.link_id)
    else:
        link = TestSkuLink(id=uid(), event_id=payload.selection.event_id, participant_key=payload.selection.participant_key)
        db.add(link)
        db.flush()
    row_id = uid()
    declaration = payload.action in ('create', 'revise')
    state = 'reviewed' if payload.action == 'review' else 'revoked' if payload.action == 'revoke' else 'pending_review'
    binding = previous.binding if payload.action == 'revoke' else proposed['binding']
    after = {'revision': proposed['revision'] + 1, 'review_state': state,
             'declaration_revision_id': row_id if declaration else previous.declaration_revision_id,
             'declared_by_user_id': actor.id if declaration else previous.declared_by_user_id}
    row = TestSkuLinkRevision(id=row_id, link_id=link.id, revision=after['revision'], action=payload.action,
        review_state=state, declaration_revision_id=after['declaration_revision_id'],
        declared_by_user_id=after['declared_by_user_id'], selection=proposed['selection'], materials=proposed['materials'],
        evidence_level=payload.evidence_level, frozen_evidence=proposed['frozen_evidence'],
        material_evidence=proposed['material_evidence'], assertions=proposed['assertions'], checks=proposed['checks'],
        binding=binding, binding_hash=digest(binding), before=event_summary(previous) if previous else None, after=after,
        attestation={'acknowledged': True, 'opened_materials': [m.model_dump() for m in payload.opened_materials],
            'confirmed_event_revision_id': payload.confirmed_event_revision_id,
            'confirmed_participant_hash': payload.confirmed_participant_hash},
        operator=payload.operator, reason=payload.reason, actor_user_id=actor.id, actor_session_id=session_id,
        idempotency_key=key, request_hash=request_hash, created_at=utcnow())
    row.fingerprint = revision_fingerprint(row)
    db.add(row)
    db.flush()
    shared.audit(session_id, 'test_sku_link_revision_appended', link_id=link.id, revision_id=row.id,
                 revision=row.revision, action_kind=row.action, actor_user_id=actor.id)
    result = {'link': link_view(db, row, actor, history=True), 'event': event_summary(row), 'idempotent_replay': False}
    db.commit()
    return result


def register_test_sku_link_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/test-sku-links/materials')
    def materials(response: Response, mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0),
                  db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        ids = db.scalars(select(EvidenceDocument.id).where(EvidenceDocument.content_type == 'application/pdf')
                        .order_by(desc(EvidenceDocument.created_at), desc(EvidenceDocument.id)).offset(offset).limit(50)).all()
        items = []
        for document_id in ids:
            _row, _blob, metadata, metadata_hash = material_metadata(db, document_id)
            items.append({**metadata, 'metadata_hash': metadata_hash})
        return {'scope': 'local_workspace', 'items': items, 'offset': offset,
            'total': db.scalar(select(func.count()).select_from(EvidenceDocument).where(EvidenceDocument.content_type == 'application/pdf')) or 0,
            'boundary': deepcopy(BOUNDARY)}

    @app.post('/v1/test-sku-links/preview', dependencies=[Depends(admin_guard)])
    def preview(payload: BridgePreviewRequest, request: Request, response: Response, db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        with db.no_autoflush:
            result = preview_link(db, payload, current_user(db, request.state.session_id))
            db.rollback()
            after = preview_link(db, payload, current_user(db, request.state.session_id))
            if result['fingerprint'] != after['fingerprint']:
                fail('test_sku_link_binding_changed')
            return result

    @app.post('/v1/test-sku-links/decisions', status_code=201, dependencies=[Depends(admin_guard)])
    def decide(payload: BridgeDecision, request: Request, response: Response,
               idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        return append_link_revision(db, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/test-sku-links')
    def listing(request: Request, response: Response, mode: Literal['history'] = Query(...),
                event_id: str | None = Query(None, max_length=64), offset: int = Query(0, ge=0), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        query = select(TestSkuLink)
        if event_id is not None:
            query = query.where(TestSkuLink.event_id == event_id)
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        links = db.scalars(query.order_by(desc(TestSkuLink.created_at), desc(TestSkuLink.id)).offset(offset).limit(50)).all()
        actor = current_user(db, request.state.session_id)
        return {'schema': SCHEMA, 'scope': 'local_workspace', 'offset': offset, 'total': total,
            'items': [link_view(db, latest_revision(db, link.id), actor) for link in links], 'boundary': deepcopy(BOUNDARY)}

    @app.get('/v1/test-sku-links/{link_id}')
    def read(link_id: str, request: Request, response: Response, mode: Literal['history'] = Query(...),
             revision: int | None = Query(None, ge=1), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        row = (latest_revision(db, link_id) if revision is None else checked_revision(db.scalar(select(TestSkuLinkRevision)
            .where(TestSkuLinkRevision.link_id == link_id, TestSkuLinkRevision.revision == revision))))
        return link_view(db, row, current_user(db, request.state.session_id), history=True)
