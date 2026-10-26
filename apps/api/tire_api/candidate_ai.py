"""Specification candidate assistance with independent rights and one-use consent."""
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import desc, select

from .ai_evidence import (PackBuilder, shared_field_materials, require_frozen_field_contract,
    require_frozen_identity_contracts)
from .ai_gateway import (GatewayError, configured_model, request_body)
from .ai_models import AICompletion, AIEvidencePack, AIRequest
from .auth import current_user, make_admin_guard, session_scope
from .candidate_ai_contract import (AuthorizationRequest, PrepareCandidateAI, SubmitCandidateAI,
    CLAIM_PLAN_KEY, IDENTITY_FIELDS, NOTICE, OUTPUT_SCHEMA, PREPARATION_SCHEMA, PROMPT_VERSION,
    PURPOSE, RECOMMENDATION_SCHEMA, REQUIREMENT_FIELDS, SYSTEM_PROMPT, validate_answer)
from .candidate_ai_models import CandidateAIAuthorization, CandidateAIClaim, CandidateAIPreparation
from .db import Snapshot, uid, utc, utcnow
from .domain import digest, stable_json
from .recommendation_candidates import FitmentCandidatesRequest, projection
from .service import QueryService, provenance, timestamp


def fail(code, status=409):
    raise HTTPException(status, {'code': code, 'message': '规格候选辅助条件不符，请重新核对准备、许可与本人同意。'},
        headers={'Cache-Control': 'no-store'})


def actor(db, session_id):
    user = current_user(db, session_id)
    if user is None:
        fail('candidate_ai_actor_required', 401)
    return user.id


def preparation_for_pack(db, pack_id):
    # Structural discrimination MUST precede owner matching, across every entry.
    return db.scalar(select(CandidateAIPreparation).where(CandidateAIPreparation.pack_id == pack_id))


def reject_candidate_pack(db, pack_id):
    if preparation_for_pack(db, pack_id) is not None:
        fail('candidate_ai_dedicated_route_required', 422)


def reject_candidate_request(db, row):
    if row is not None:
        reject_candidate_pack(db, row.pack_id)


def owned_preparation(db, identifier, session_id):
    row = db.get(CandidateAIPreparation, identifier)
    owner = actor(db, session_id)
    if row is None or row.actor_user_id != owner:
        fail('candidate_ai_preparation_not_found', 404)
    return checked_preparation(row)


def checked_preparation(row):
    if row is None:
        fail('candidate_ai_preparation_not_found', 404)
    if digest({'request': row.request, 'binding': row.binding, 'view': row.view,
            'actor_user_id': row.actor_user_id, 'pack_id': row.pack_id}) != row.fingerprint:
        fail('candidate_ai_preparation_integrity_failed')
    return row


def authorization_scope(dependency_id, provider):
    return digest({'dependency_id': dependency_id, 'provider': provider, 'purpose': PURPOSE})


def recipient_fingerprint(config):
    return digest({'provider': config.provider, 'endpoint': config.endpoint, 'allowed_host': config.allowed_host})


def authorization_head(db, dependency_id, provider):
    row = db.scalar(select(CandidateAIAuthorization).where(
        CandidateAIAuthorization.scope_hash == authorization_scope(dependency_id, provider))
        .order_by(desc(CandidateAIAuthorization.revision)).limit(1).execution_options(populate_existing=True))
    if row is not None and digest({'scope_hash': row.scope_hash, 'revision': row.revision,
            'actor_user_id': row.actor_user_id, 'payload': row.payload}) != row.fingerprint:
        fail('candidate_ai_authorization_integrity_failed')
    return row


def authorization_view(row):
    if row is None:
        return None
    expired = utc(datetime.fromisoformat(row.payload['expires_at'])) <= utcnow()
    return {'state': 'expired' if row.payload['action'] == 'grant' and expired else
        'granted' if row.payload['action'] == 'grant' else 'revoked',
        'revision_id': row.id, 'revision': row.revision, 'expires_at': row.payload['expires_at']}


def dependency(kind, snapshot_id, raw_hash, value):
    def leaves(node, pointer=''):
        if isinstance(node, dict) and node:
            return [field for key in sorted(node) for field in leaves(node[key], pointer + '/' +
                key.replace('~', '~0').replace('/', '~1'))]
        if isinstance(node, list) and node:
            return [field for index, child in enumerate(node) for field in leaves(child, pointer + '/' + str(index))]
        return [pointer]
    fields = sorted(leaves(value))
    result = {'source_kind': kind, 'snapshot_id': snapshot_id, 'raw_hash': raw_hash,
        'projection_hash': digest(value), 'fields': fields}
    return {'id': digest(result), **result}


def _reason(variant_id, relation, selection, field, value, text):
    reference = {'variant_id': variant_id, 'relation_id': relation['relation_id'],
        'relation_revision_id': relation['revision_id'], 'relation_revision': relation['revision'],
        'selection': selection, 'field': field, 'status': 'match', 'value': deepcopy(value)}
    return {'id': digest({'purpose': PURPOSE, 'reference': reference}), 'text': text, 'reference': reference}


def build_snapshot(db, registry, payload, session_id):
    owner = actor(db, session_id)
    projected, signature = projection(db, session_id, FitmentCandidatesRequest(
        selection=payload.selection, expected_preference_revision=payload.expected_preference_revision,
        expected_preference_fingerprint=payload.expected_preference_fingerprint))
    if projected['truncated']:
        fail('candidate_ai_candidate_scope_incomplete')
    if projected['preference']['weights'] is None:
        fail('candidate_ai_preference_required')
    available = {item['variant_id']: item for item in projected['items']}
    if not set(payload.variant_ids) <= available.keys():
        fail('candidate_ai_selection_unavailable')
    selection = payload.selection.model_dump()
    dependencies, candidates, outbound_candidates = {}, [], []
    for identifier in payload.variant_ids:
        item = available[identifier]
        identity = {key: deepcopy(value) for key, value in item['identity'].items() if key in IDENTITY_FIELDS}
        if set(identity) != set(item['identity']):
            fail('candidate_ai_identity_fields_unsupported')
        reasons, unknown, relations = [], [], []
        for relation in item['relations']:
            from .fitment_relation_models import FitmentRelationRevision
            original_relation = db.get(FitmentRelationRevision, relation['revision_id'])
            if original_relation is None:
                fail('candidate_ai_relation_unavailable')
            vehicle, tire = relation['vehicle_evidence'], relation['tire_evidence']
            requirements = {key: deepcopy(value) for key, value in vehicle['requirements'].items()
                if key in REQUIREMENT_FIELDS}
            checks = [{key: deepcopy(check[key]) for key in ('field', 'status', 'vehicle_value', 'tire_value')}
                for check in relation['checks'] if check['field'] in REQUIREMENT_FIELDS]
            if any(check['status'] not in ('match', 'unknown', 'not_declared') for check in checks):
                fail('candidate_ai_relation_checks_invalid')
            unknown.extend(check['field'] for check in checks if check['status'] != 'match')
            reasons.append(_reason(identifier, relation, selection, 'relation.review_state', 'reviewed',
                '存在仍有效的已审本地轴位关系；不代表官方原配或安装安全。'))
            for check in checks:
                if check['status'] == 'match':
                    reasons.append(_reason(identifier, relation, selection, check['field'], check['tire_value'],
                        '该字段原值与所选车型轴位要求一致；不表示性能优势。'))
            vehicle_value = {'selection': selection, 'requirements': requirements,
                'check_values': {check['field']: deepcopy(check['vehicle_value']) for check in checks}}
            tire_value = {'variant_id': identifier, 'identity': identity}
            reference = {'relation_id': relation['relation_id'], 'revision_id': relation['revision_id'],
                'revision': relation['revision'], 'selection': {**selection, **{key: relation['selection'][key]
                    for key in ('variant_id', 'tire_snapshot_id', 'fact_version_id')}},
                'checks': checks, 'acknowledged_unknowns': relation['acknowledged_unknowns']}
            relations.append(reference)
            for dep in (
                dependency('vehicle', selection['vehicle_snapshot_id'], vehicle['provenance']['raw_hash'], vehicle_value),
                dependency('tire', relation['selection']['tire_snapshot_id'], tire['provenance']['raw_hash'], tire_value),
                dependency('relation', relation['revision_id'], digest({column.name:
                    timestamp(getattr(original_relation, column.name)) if isinstance(getattr(original_relation, column.name), datetime)
                    else getattr(original_relation, column.name) for column in original_relation.__table__.columns}), reference)):
                dependencies[dep['id']] = dep
        candidates.append({'variant_id': identifier, 'identity': identity, 'reasons': reasons,
            'unknown_fields': sorted(set(unknown))})
        outbound_candidates.append({'variant_id': identifier, 'identity': identity, 'relations': relations,
            'reasons': reasons, 'unknown_fields': sorted(set(unknown))})
    outbound = {'schema': 'candidate-ai-outbound@1', 'purpose': PURPOSE, 'selection': selection,
        'preference': projected['preference'], 'candidates': outbound_candidates,
        'ranking': 'not_computed', 'performance_score': None, 'performance_evidence': 'not_established'}
    binding = {'actor_user_id': owner, 'candidate_signature': signature, 'preference': projected['preference'],
        'dependencies': list(dependencies.values()), 'outbound_hash': digest(outbound)}
    return {'owner': owner, 'selection': selection, 'preference': projected['preference'],
        'candidates': candidates, 'dependencies': list(dependencies.values()), 'outbound': outbound,
        'binding': binding, 'projection': projected}


def provider_context(question, outbound):
    try:
        config = configured_model()
        policy = {'provider': config.provider, 'model': config.model, 'endpoint': config.endpoint,
            'allowed_host': config.allowed_host, 'allow_private': config.allow_private,
            'max_output_tokens': config.max_output_tokens, 'daily_token_limit': config.daily_token_limit,
            'daily_request_limit': config.daily_request_limit, 'response_format': config.response_format,
            'tokens_param': config.tokens_param, 'stream_usage': config.stream_usage, 'auth_style': config.auth_style,
            'purpose': PURPOSE, 'prompt_version': PROMPT_VERSION, 'prompt_hash': digest(SYSTEM_PROMPT),
            'output_schema_hash': digest(OUTPUT_SCHEMA)}
        body, reserve = request_body(config, question, outbound, system_prompt=SYSTEM_PROMPT,
            output_schema=OUTPUT_SCHEMA, schema_name='candidate_spec_selection')
        return config, body, {'provider': config.provider, 'model': config.model, 'state': 'configured',
            'endpoint_host': config.allowed_host, 'policy_fingerprint': digest(policy),
            'body_hash': digest(body), 'reserved_tokens': reserve}
    except GatewayError:
        return None, None, None


def _pack(db, registry, snapshot, request, pack_id, session_id, expires):
    """Keep the existing warehouse identity/field gates; this full local pack is never dispatched."""
    from .field_authority import policy_descriptor, resolve_fields
    from .field_evidence import complete_missing_candidates
    from .identity_contract import contract_context, contract_metadata
    builder, seen = PackBuilder(), set()
    wanted = set(request.variant_ids)
    for item in snapshot['projection']['items']:
        if item['variant_id'] not in wanted:
            continue
        for relation in item['relations']:
            key = (item['variant_id'], relation['selection']['tire_snapshot_id'])
            if key in seen:
                continue
            seen.add(key)
            archived = db.get(Snapshot, key[1])
            member = next(value for value in archived.parsed_variants if value['id'] == key[0])
            builder.tire(db, member, {**provenance(archived), 'data_state': 'local_snapshot',
                'verified_at': None, 'consent_id': None}, registry)
    resolutions = []
    for identifier, rows in sorted(builder.field_candidates.items()):
        completed = complete_missing_candidates(rows)
        for value in completed:
            if not value['present']:
                value['fact_ids'] = []
        resolutions.append(resolve_fields(completed, variant_id=identifier, scope='selected_evidence', data_state='local_snapshot'))
    context = contract_context(db, wanted)
    for evidence in builder.evidence:
        evidence['identity_contract'] = contract_metadata(db, evidence['variant_id'], context=context)
    content = {'purpose': PURPOSE, 'retrieval': 'exact_structured_lookup', 'field_policy': policy_descriptor(),
        'field_resolutions': resolutions, 'evidence': builder.evidence, 'facts': builder.facts,
        'conflicts': builder.conflicts, 'source_state': 'snapshot', 'query_id': None, 'consent_id': None,
        'candidate_binding': snapshot['binding'], 'candidate_outbound_hash': digest(snapshot['outbound'])}
    if not builder.evidence or {item['variant_id'] for item in builder.evidence} != wanted:
        fail('candidate_ai_evidence_incomplete')
    require_frozen_field_contract(content)
    require_frozen_identity_contracts(db, builder.evidence)
    row = AIEvidencePack(id=pack_id, actor_session_id=session_id, mode='history', data_state='local_snapshot',
        privacy_class='private', payload=content, fingerprint=digest(content), expires_at=expires)
    db.add(row)
    return row


def prepare_candidate(db, registry, payload, session_id):
    first = build_snapshot(db, registry, payload, session_id)
    db.rollback()
    db.expire_all()
    QueryService(db, None).lock_ingestion()
    snapshot = build_snapshot(db, registry, payload, session_id)
    if first['binding'] != snapshot['binding']:
        fail('candidate_ai_binding_changed')
    config, body, provider = provider_context(payload.question, snapshot['outbound'])
    blockers, dependencies = [], []
    if provider is None:
        blockers.append('candidate_ai_provider_unavailable')
    elif not config.allow_private:
        blockers.append('candidate_ai_private_processing_forbidden')
    for dep in snapshot['dependencies']:
        head = authorization_head(db, dep['id'], config.provider) if config else None
        auth = authorization_view(head)
        dependencies.append({**dep, 'authorization': auth})
        if auth is None or auth['state'] != 'granted':
            blockers.append('candidate_ai_dependency_permission_missing')
        elif head.payload.get('recipient_fingerprint') != recipient_fingerprint(config):
            blockers.append('candidate_ai_permission_recipient_mismatch')
    now = utcnow()
    expires = now + timedelta(minutes=30)
    for dep in dependencies:
        if dep['authorization'] and dep['authorization']['state'] == 'granted':
            expires = min(expires, utc(datetime.fromisoformat(dep['authorization']['expires_at'])))
    preparation_id, pack_id = uid(), uid()
    binding = {**snapshot['binding'], 'dependencies': dependencies, 'provider': provider}
    fingerprint = digest({'purpose': PURPOSE, 'request': payload.model_dump(), 'binding': binding})
    consent = None if blockers else digest({'purpose': PURPOSE, 'actor_user_id': snapshot['owner'],
        'preparation_id': preparation_id, 'pack_id': pack_id, 'preparation_fingerprint': fingerprint,
        'question_hash': digest(payload.question), 'provider': provider})
    view = {'schema': PREPARATION_SCHEMA, 'purpose': PURPOSE, 'preparation_id': preparation_id,
        'pack_id': pack_id, 'fingerprint': fingerprint, 'selection': snapshot['selection'],
        'preference': snapshot['preference'], 'candidates': snapshot['candidates'], 'dependencies': dependencies,
        'blockers': list(dict.fromkeys(blockers)), 'provider': provider, 'consent_hash': consent,
        'expires_at': timestamp(expires), 'sendable': not blockers}
    pack = _pack(db, registry, snapshot, payload, pack_id, session_id, expires)
    row = CandidateAIPreparation(id=preparation_id, actor_session_id=session_id, actor_user_id=snapshot['owner'],
        pack_id=pack.id, request=payload.model_dump(), binding=binding, view=view, expires_at=expires,
        fingerprint=digest({'request': payload.model_dump(), 'binding': binding, 'view': view,
            'actor_user_id': snapshot['owner'], 'pack_id': pack.id}))
    db.add(row)
    QueryService(db, None).audit(session_id, 'candidate_ai_preparation_created', preparation_id=row.id, fingerprint=fingerprint)
    db.commit()
    return deepcopy(view)


def check_fresh(db, registry, row, session_id):
    if actor(db, session_id) != row.actor_user_id or utc(row.expires_at) <= utcnow():
        fail('candidate_ai_preparation_stale')
    payload = PrepareCandidateAI.model_validate(row.request)
    snapshot = build_snapshot(db, registry, payload, session_id)
    config, body, provider = provider_context(payload.question, snapshot['outbound'])
    dependencies = [{**dep, 'authorization': authorization_view(authorization_head(db, dep['id'], config.provider))
        if config else None} for dep in snapshot['dependencies']]
    binding = {**snapshot['binding'], 'dependencies': dependencies, 'provider': provider}
    if binding != row.binding:
        fail('candidate_ai_preparation_stale')
    if (not row.view['sendable'] or row.view['consent_hash'] is None or provider is None or not config.allow_private
            or any(dep['authorization'] is None or dep['authorization']['state'] != 'granted' for dep in dependencies)):
        fail('candidate_ai_processing_not_authorized', 403)
    if any(authorization_head(db, dep['id'], config.provider).payload.get('recipient_fingerprint') !=
            recipient_fingerprint(config) for dep in dependencies):
        fail('candidate_ai_permission_recipient_mismatch', 403)
    pack = db.get(AIEvidencePack, row.pack_id)
    if (pack is None or pack.fingerprint != digest(pack.payload) or not pack.payload.get('evidence')
            or pack.payload.get('purpose') != PURPOSE or pack.privacy_class != 'private'
            or pack.payload.get('candidate_binding') != snapshot['binding']
            or pack.payload.get('candidate_outbound_hash') != digest(snapshot['outbound'])):
        fail('candidate_ai_pack_integrity_failed')
    require_frozen_identity_contracts(db, pack.payload['evidence'])
    require_frozen_field_contract(pack.payload)
    return pack, config, body, provider


def reserve_gate(db, pack, session_id):
    row = preparation_for_pack(db, pack.id)
    if row is None:
        return None
    plan = db.info.pop(CLAIM_PLAN_KEY, None)
    if (actor(db, session_id) != row.actor_user_id or not isinstance(plan, dict)
            or plan.get('preparation_id') != row.id or plan.get('consent_hash') != row.view['consent_hash']):
        fail('candidate_ai_dedicated_claim_required', 422)
    if db.scalar(select(CandidateAIClaim.id).where(CandidateAIClaim.preparation_id == row.id)) is not None:
        fail('candidate_ai_preparation_consumed')
    return row, plan


def claim_reserved(db, reserved, gate):
    if gate is not None:
        preparation, plan = gate
        db.add(CandidateAIClaim(preparation_id=preparation.id, request_id=reserved.id,
            actor_user_id=preparation.actor_user_id, consent_hash=plan['consent_hash'],
            idempotency_key=reserved.idempotency_key, request_fingerprint=request_fingerprint(reserved)))
        db.flush()


def request_fingerprint(row):
    # Bind every reserved request column before commit, including the actual
    # submitting session and complete provider contract. The append-only claim
    # remains authoritative if the legacy request table is damaged by raw SQL.
    return digest({column.name: timestamp(value) if isinstance(value, datetime) else value
        for column in AIRequest.__table__.columns for value in [getattr(row, column.name)]})


def before_dispatch(db, app, request_row, config, body):
    """Last authoritative fence at the actual adapter boundary; no testing hook."""
    preparation = preparation_for_pack(db, request_row.pack_id)
    if preparation is None:
        return
    try:
        db.rollback()
        db.expire_all()
        preparation = owned_preparation(db, preparation.id, request_row.actor_session_id)
        claim = db.scalar(select(CandidateAIClaim).where(CandidateAIClaim.request_id == request_row.id))
        if (claim is None or claim.preparation_id != preparation.id
                or claim.actor_user_id != preparation.actor_user_id
                or claim.consent_hash != preparation.view['consent_hash']
                or claim.request_fingerprint != request_fingerprint(request_row)):
            fail('candidate_ai_dedicated_claim_required')
        _pack_row, fresh_config, fresh_body, provider = check_fresh(db, app.state.registry, preparation, request_row.actor_session_id)
        if (digest(body) != digest(fresh_body) or request_row.request_contract.get('body_hash') != digest(body)
                or provider['policy_fingerprint'] != request_row.request_contract.get('provider_policy_fingerprint')
                or config != fresh_config):
            fail('candidate_ai_pre_dispatch_changed')
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError):
        db.rollback()
        raise GatewayError('candidate_ai_pre_dispatch_changed') from None


def _key(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail('candidate_ai_idempotency_key_invalid', 422)


def result_view(db, request_row, session_id, registry):
    preparation = preparation_for_pack(db, request_row.pack_id)
    if preparation is None or actor(db, session_id) != preparation.actor_user_id:
        fail('candidate_ai_recommendation_not_found', 404)
    preparation = owned_preparation(db, preparation.id, session_id)
    from .ai_analysis import run_state
    try:
        claim = db.scalar(select(CandidateAIClaim).where(CandidateAIClaim.request_id == request_row.id))
        provider = preparation.view['provider']
        expected_contract = {'purpose': PURPOSE, 'prompt_version': PROMPT_VERSION,
            'preparation_id': preparation.id, 'preparation_fingerprint': preparation.view['fingerprint'],
            'consent_hash': preparation.view['consent_hash'],
            'provider_policy_fingerprint': provider['policy_fingerprint'], 'body_hash': provider['body_hash'], 'store': False}
        if (claim is None or claim.preparation_id != preparation.id or claim.actor_user_id != preparation.actor_user_id
                or claim.consent_hash != preparation.view['consent_hash'] or claim.idempotency_key != request_row.idempotency_key
                or claim.request_fingerprint != request_fingerprint(request_row)
                or request_row.question != preparation.request['question']
                or request_row.provider != provider['provider'] or request_row.model != provider['model']
                or request_row.reserved_tokens != provider['reserved_tokens']
                or request_row.request_hash != digest({'purpose': PURPOSE, 'preparation_id': preparation.id,
                    'consent_hash': preparation.view['consent_hash'], 'allow_external_processing': True})
                or set(request_row.request_contract) != {*expected_contract, 'max_output_tokens'}
                or any(request_row.request_contract[key] != value for key, value in expected_contract.items())):
            raise ValueError('candidate_ai_history_binding_invalid')
        completion = db.get(AICompletion, request_row.id)
        if completion is not None:
            if completion.state == 'completed' and completion.error_code is None:
                answer = completion.answer
                model = {'decision': answer['decision'], 'selections': [
                    {'variant_id': chosen['variant_id'], 'reason_ids': [reason['id'] for reason in chosen['reasons']]}
                    for chosen in answer['selections']],
                    'uncertainty_codes': [item['code'] for item in answer['uncertainty']]}
                if digest(answer) != digest(validate_answer(stable_json(model), preparation.view)):
                    raise ValueError('candidate_ai_history_answer_invalid')
            elif completion.state != 'failed' or completion.answer is not None or not completion.error_code:
                raise ValueError('candidate_ai_history_completion_invalid')
    except (ValueError, TypeError, KeyError, AttributeError):
        fail('candidate_ai_history_integrity_failed')
    value = run_state(db, request_row)
    status = {'state': 'unchanged', 'blockers': []}
    try:
        check_fresh(db, registry, preparation, session_id)
    except HTTPException as error:
        status = {'state': 'stale', 'blockers': [error.detail.get('code', 'candidate_ai_preparation_stale')
            if isinstance(error.detail, dict) else 'candidate_ai_preparation_stale']}
    return {key: value[key] for key in ('id', 'pack_id', 'state', 'usage', 'reserved_tokens', 'error_code',
        'created_at', 'completed_at', 'answer')} | {'schema': RECOMMENDATION_SCHEMA, 'purpose': PURPOSE,
        'current': False, 'preparation': deepcopy(preparation.view), 'current_status': status}


def register_candidate_ai_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db
    admin_guard = make_admin_guard(get_db)

    @app.post('/v1/ai/candidate-preparations')
    def prepare(payload: PrepareCandidateAI, request: Request, response: Response, db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        return prepare_candidate(db, app.state.registry, payload, request.state.session_id)

    @app.post('/v1/ai/candidate-preparations/{preparation_id}/authorizations', dependencies=[Depends(admin_guard)])
    def authorize(preparation_id: str, payload: AuthorizationRequest, request: Request, response: Response, db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        QueryService(db, None).lock_ingestion()
        preparation = (owned_preparation(db, preparation_id, request.state.session_id) if payload.action == 'grant'
            else checked_preparation(db.get(CandidateAIPreparation, preparation_id)))
        issuer = actor(db, request.state.session_id)
        if payload.dependency_id not in {dep['id'] for dep in preparation.view['dependencies']}:
            fail('candidate_ai_dependency_not_found', 404)
        if payload.action == 'grant':
            current = build_snapshot(db, app.state.registry, PrepareCandidateAI.model_validate(preparation.request), request.state.session_id)
            if (utc(preparation.expires_at) <= utcnow()
                    or current['binding']['candidate_signature'] != preparation.binding['candidate_signature']
                    or payload.dependency_id not in {dep['id'] for dep in current['dependencies']}):
                fail('candidate_ai_preparation_stale')
            try:
                config = configured_model()
            except GatewayError:
                fail('candidate_ai_provider_unavailable', 422)
            if payload.provider != config.provider:
                fail('candidate_ai_authorization_provider_mismatch', 422)
        previous = authorization_head(db, payload.dependency_id, payload.provider)
        if payload.expected_revision != (previous.revision if previous else 0):
            fail('candidate_ai_authorization_revision_conflict')
        if payload.action == 'grant':
            try:
                expires = datetime.fromisoformat(payload.expires_at.replace('Z', '+00:00'))
                if expires.tzinfo is None:
                    raise ValueError()
                expires = utc(expires)
            except (ValueError, TypeError):
                fail('candidate_ai_authorization_expiry_invalid', 422)
            if expires <= utcnow():
                fail('candidate_ai_authorization_expiry_invalid', 422)
            data = {**payload.model_dump(), 'expires_at': timestamp(expires), 'purpose': PURPOSE,
                'recipient_fingerprint': recipient_fingerprint(config)}
        else:
            if previous is None:
                fail('candidate_ai_authorization_missing')
            data = {**previous.payload, **payload.model_dump()}
        row = CandidateAIAuthorization(scope_hash=authorization_scope(payload.dependency_id, payload.provider),
            revision=payload.expected_revision + 1, actor_user_id=issuer, payload=data,
            fingerprint=digest({'scope_hash': authorization_scope(payload.dependency_id, payload.provider),
                'revision': payload.expected_revision + 1, 'actor_user_id': issuer, 'payload': data}))
        db.add(row)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'candidate_ai_rights_revised', authorization_id=row.id,
            revision=row.revision, action_kind=payload.action, dependency_id=payload.dependency_id,
            **({'revocation_note': payload.revocation_note} if payload.action == 'revoke' else {}))
        db.commit()
        return {'schema': 'candidate-ai-authorization@1', 'dependency_id': payload.dependency_id,
            'provider': payload.provider, 'purpose': PURPOSE, **authorization_view(row),
            'recipient_fingerprint': data['recipient_fingerprint'],
            **{key: data[key] for key in ('rights_holder', 'license_basis_url', 'license_basis_note', 'license_evidence_sha256')}}

    @app.post('/v1/ai/candidate-recommendations')
    def generate(payload: SubmitCandidateAI, request: Request, response: Response,
                 idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        from .ai_execution import execute_response, reserve_response
        response.headers['Cache-Control'] = 'no-store'
        key = _key(idempotency_key)
        owner = actor(db, request.state.session_id)
        fingerprint = digest({'purpose': PURPOSE, **payload.model_dump()})
        QueryService(db, None).lock_ingestion()
        previous = db.scalar(select(AIRequest).where(AIRequest.actor_session_id.in_(session_scope(db, request.state.session_id)),
            AIRequest.idempotency_key == key))
        if previous is not None:
            if previous.request_hash != fingerprint or preparation_for_pack(db, previous.pack_id) is None:
                fail('candidate_ai_idempotency_payload_mismatch')
            db.commit()
            return result_view(db, previous, request.state.session_id, app.state.registry)
        row = owned_preparation(db, payload.preparation_id, request.state.session_id)
        if not payload.allow_external_processing or payload.consent_hash != row.view['consent_hash']:
            fail('candidate_ai_consent_mismatch', 422)
        pack, config, body, provider = check_fresh(db, app.state.registry, row, request.state.session_id)
        db.info[CLAIM_PLAN_KEY] = {'preparation_id': row.id, 'consent_hash': payload.consent_hash}
        reserved = reserve_response(db, config=config, pack=pack, session_id=request.state.session_id, key=key,
            request_hash=fingerprint, question=row.request['question'], reserve=provider['reserved_tokens'], body=body,
            contract={'purpose': PURPOSE, 'prompt_version': PROMPT_VERSION, 'preparation_id': row.id,
                'preparation_fingerprint': row.view['fingerprint'], 'consent_hash': payload.consent_hash,
                'provider_policy_fingerprint': provider['policy_fingerprint']})
        # Durable reservation has committed. Use a genuinely new read transaction
        # before entering the actual adapter; a failure must leave a completion.
        db.rollback()
        db.expire_all()
        try:
            current = owned_preparation(db, row.id, request.state.session_id)
            _pack_row, new_config, new_body, new_provider = check_fresh(db, app.state.registry, current, request.state.session_id)
            if owner != current.actor_user_id or provider != new_provider or digest(body) != digest(new_body):
                fail('candidate_ai_pre_dispatch_changed')
        except HTTPException:
            db.rollback()
            db.add(AICompletion(request_id=reserved.id, state='failed', error_code='candidate_ai_pre_dispatch_changed',
                answer=None, usage=None, provider_response_id=None))
            db.commit()
        else:
            execute_response(db, app, reserved, new_config, new_body, lambda text: validate_answer(text, current.view))
        return result_view(db, reserved, request.state.session_id, app.state.registry)

    @app.get('/v1/ai/candidate-recommendations')
    def lookup(request: Request, response: Response, key: str = Query(..., max_length=64),
               mode: str = Query(..., pattern='^history$'), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        actor(db, request.state.session_id)
        row = db.scalar(select(AIRequest).where(AIRequest.actor_session_id.in_(session_scope(db, request.state.session_id)),
            AIRequest.idempotency_key == _key(key)))
        if row is None:
            fail('candidate_ai_recommendation_not_found', 404)
        return result_view(db, row, request.state.session_id, app.state.registry)

    @app.get('/v1/ai/candidate-recommendations/{identifier}')
    def detail(identifier: str, request: Request, response: Response,
               mode: str = Query(..., pattern='^history$'), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        row = db.get(AIRequest, identifier)
        if row is None:
            fail('candidate_ai_recommendation_not_found', 404)
        return result_view(db, row, request.state.session_id, app.state.registry)
