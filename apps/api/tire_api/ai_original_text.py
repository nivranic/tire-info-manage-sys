"""Original-bound excerpts and purpose-scoped use through existing AI ledgers."""
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import TypeAdapter

from .ai_gateway import GatewayError, configured_model
from .auth import current_user, make_admin_guard
from .domain import digest
from .service import QueryService
from .text_embedding_models import TextEmbeddingAuthorization
from .text_embeddings import (AuthorizationRequest, PreviewRequest, TextSelection,
    authorization_head, authorization_view, original_excerpt)

POLICY = 'original-text-grounding@1'
AI_PURPOSE = 'original_text_ai@1'
EXPORT_PURPOSE = 'original_text_report_export@1'
TEXT_KINDS = frozenset({'source_text', 'document_text'})
LOCAL_ERRORS = frozenset({'ai_original_text_binding_failed', 'ai_original_text_original_invalid',
    'ai_original_text_use_not_allowed'})
NOTICE = ('原文摘录保留页面或PDF页码范围，来源中的陈述及指令作为来源内容处理。'
    '具体SKU、测试身份及适用性需对应结构化证据，PDF留存时间与发布时间各按已有元信息表达。')
selection_adapter = TypeAdapter(TextSelection)


def fail(code='ai_original_text_binding_failed', status=409):
    raise HTTPException(status, {'code': code, 'message': '请重新核对所选正文原件、用途许可和接收端。'})


class TextUsePreview(PreviewRequest):
    purpose: Literal['original_text_ai@1', 'original_text_report_export@1'] = AI_PURPOSE


class TextUseAuthorization(AuthorizationRequest):
    purpose: Literal['original_text_ai@1', 'original_text_report_export@1'] = AI_PURPOSE


def recipient(purpose, config=None):
    if purpose == EXPORT_PURPOSE:
        return {'destination': 'research_report_download', 'formats': ['markdown', 'html', 'pdf']}
    if purpose != AI_PURPOSE or config is None:
        fail()
    return {'provider': config.provider, 'endpoint': config.endpoint, 'allowed_host': config.allowed_host}


def scope_for(selection, purpose, receiving):
    return digest({'purpose': purpose, 'selection': selection.model_dump(), 'recipient': receiving})


def permission(db, selection, purpose, receiving):
    scope = scope_for(selection, purpose, receiving)
    try:
        row = authorization_head(db, scope)
        if row is not None and (row.payload['purpose'] != purpose
                or row.payload['selection'] != selection.model_dump() or row.payload['recipient'] != receiving):
            fail()
        view = authorization_view(row)
    except (KeyError, TypeError, ValueError):
        fail()
    except HTTPException as error:
        if isinstance(error.detail, dict) and error.detail.get('code') in LOCAL_ERRORS:
            raise
        fail()
    return row, view


def excerpt_for(db, selected, pdfs):
    try:
        return original_excerpt(db, selected, pdfs)
    except HTTPException:
        fail('ai_original_text_original_invalid')


def evidence_for(excerpt):
    selected = {'kind': excerpt['kind'], 'reference': excerpt['reference']}
    common = {'kind': excerpt['kind'], 'original_text': {'selection': selected, 'text_hash': digest(excerpt['text'])},
        'raw_hash': excerpt['reference']['raw_hash'], 'parser_version': excerpt['reference']['extractor_version'],
        'data_state': 'local_snapshot', 'verification_status': 'original_text_excerpt', 'notice': NOTICE}
    if excerpt['kind'] == 'source_text':
        return {**common, 'label': excerpt['source_id'] + ' · 页面原文摘录',
            'source_id': excerpt['source_id'], 'source_url': excerpt['source_url'],
            'snapshot_id': excerpt['reference']['snapshot_id'], 'observed_at': excerpt['observed_at'],
            'verified_at': excerpt['verified_at'], 'content_scope': 'page'}
    document = excerpt['document']
    return {**common, 'label': document['title'] + ' · 第 ' + str(excerpt['reference']['page']) + ' 页原文摘录',
        'source_url': document['source_url'], 'document_id': document['id'],
        'observed_at': None, 'verified_at': None, 'retained_at': document['created_at'],
        'content_scope': 'document_page'}


def add_original(builder, db, selected, pdfs):
    excerpt = excerpt_for(db, selected, pdfs)
    evidence = evidence_for(excerpt)
    private = True
    try:
        config = configured_model()
    except GatewayError:
        config = None
    if config is not None:
        row, view = permission(db, selected, AI_PURPOSE, recipient(AI_PURPOSE, config))
        if view['state'] == 'granted' and row.payload['text_hash'] == digest(excerpt['text']):
            private = row.payload['request']['privacy_class'] != 'public'
    builder.add(kind=evidence.pop('kind'), label=evidence.pop('label'), provenance=evidence,
        values={'原文摘录': excerpt['text']}, field_codes={'原文摘录': 'original_text.excerpt'}, private=private)


def original_items(payload):
    """Validate the frozen citation contract without consulting current source state."""
    evidence, facts = payload.get('evidence', []), payload.get('facts', [])
    if (not isinstance(evidence, list) or not isinstance(facts, list)
            or any(not isinstance(item, dict) for item in [*evidence, *facts])):
        fail()
    selected = [item for item in evidence if item.get('kind') in TEXT_KINDS or 'original_text' in item]
    if not selected:
        if payload.get('original_text_policy') is not None or any(
                str(fact.get('field_code', '')).startswith('original_text.') for fact in facts):
            fail()
        return []
    if payload.get('original_text_policy') != POLICY:
        fail()
    result = []
    try:
        for item in selected:
            original = item['original_text']
            selection = selection_adapter.validate_python(original['selection'])
            matching = [fact for fact in facts if fact['evidence_id'] == item['id']]
            if len(matching) != 1:
                fail()
            fact = matching[0]
            if (item['kind'] != selection.kind or set(original) != {'selection', 'text_hash'}
                    or not isinstance(fact['value'], str) or not fact['value']
                    or original['text_hash'] != digest(fact['value']) or fact['field'] != '原文摘录'
                    or fact['field_code'] != 'original_text.excerpt'
                    or fact['text'] != item['label'] + '：原文摘录 = ' + fact['value']):
                fail()
            result.append((item, selection, fact['value']))
    except (KeyError, TypeError, ValueError):
        fail()
    return result


def require_originals(db, payload, *, purpose=None, config=None):
    pdfs = {}
    for item, selection, value in original_items(payload):
        excerpt = excerpt_for(db, selection, pdfs)
        current = evidence_for(excerpt)
        # Later formal verification of the same saved HTML can advance verified_at.
        if (excerpt['text'] != value or set(item) != {'id', *current}
                or any(item[key] != expected for key, expected in current.items() if key != 'verified_at')):
            fail()
        if purpose is None:
            continue
        receiving = recipient(purpose, config)
        row, view = permission(db, selection, purpose, receiving)
        if view['state'] != 'granted':
            fail('ai_original_text_use_not_allowed', 403)
        request = row.payload['request']
        if row.payload['text_hash'] != digest(value) or request['privacy_class'] not in {'public', 'private'}:
            fail()
        if purpose == AI_PURPOSE and request['privacy_class'] == 'private' and not config.allow_private:
            fail('ai_original_text_use_not_allowed', 403)


def require_dispatch(database, request_id, config, body, pack=None):
    from .ai_execution import _vehicle_dispatch_input
    from .ai_models import AIEvidencePack, AIRequest
    from .auth import session_scope
    try:
        with database.sessions() as db:
            request = db.get(AIRequest, request_id)
            if request is None:
                fail()
            frozen = db.get(AIEvidencePack, request.pack_id)
            if frozen is None:
                fail()
            outbound = _vehicle_dispatch_input(body)
            marked = (request.request_contract.get('original_text_policy') is not None
                or frozen.payload.get('original_text_policy') is not None
                or outbound is not None and outbound['untrusted_evidence_pack'].get('original_text_policy') is not None)
            if not marked:
                return
            if (not original_items(frozen.payload)
                    or frozen.actor_session_id not in session_scope(db, request.actor_session_id)
                    or request.provider != config.provider or request.model != config.model
                    or digest(frozen.payload) != frozen.fingerprint
                    or request.request_contract.get('body_hash') != digest(body)
                    or outbound is None or outbound.get('question') != request.question
                    or digest(outbound['untrusted_evidence_pack']) != digest({**frozen.payload, 'data_state': frozen.data_state})
                    or pack is not None and (pack.get('data_state') != frozen.data_state
                        or digest(pack.get('payload')) != frozen.fingerprint)):
                fail()
            require_originals(db, frozen.payload, purpose=AI_PURPOSE, config=config)
    except HTTPException as error:
        code = error.detail.get('code') if isinstance(error.detail, dict) else None
        raise GatewayError(code if code in LOCAL_ERRORS else 'ai_original_text_binding_failed') from None
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GatewayError('ai_original_text_binding_failed') from None


def register_original_text_ai_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    def receiving(purpose):
        try:
            return recipient(purpose, configured_model() if purpose == AI_PURPOSE else None)
        except GatewayError as error:
            raise HTTPException(503, str(error)) from None

    @app.post('/v1/ai/text-authorizations/preview')
    def preview(payload: TextUsePreview, db=Depends(get_db)):
        target = receiving(payload.purpose)
        excerpt = excerpt_for(db, payload.selection, {})
        _row, view = permission(db, payload.selection, payload.purpose, target)
        return {'purpose': payload.purpose, 'selection': payload.selection.model_dump(),
            'text': excerpt['text'], 'text_hash': digest(excerpt['text']), 'recipient': target,
            'scope_hash': scope_for(payload.selection, payload.purpose, target), 'authorization': view,
            'notice': '管理员声明具体用途依据。向AI提交仍需个人确认本次问题及全部证据的外部处理。'}

    @app.post('/v1/ai/text-authorizations', dependencies=[Depends(admin_guard)])
    def authorize(payload: TextUseAuthorization, request: Request, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        scope = payload.scope_hash if payload.action == 'revoke' else None
        if scope is None:
            target = receiving(payload.purpose)
            scope = scope_for(payload.selection, payload.purpose, target)
        previous = authorization_head(db, scope)
        if payload.scope_hash is not None and payload.scope_hash != scope:
            fail()
        if payload.expected_revision != (previous.revision if previous else 0):
            fail()
        if previous is not None and (previous.payload['purpose'] != payload.purpose
                or scope_for(payload.selection, payload.purpose, previous.payload['recipient']) != scope):
            fail()
        if payload.action == 'revoke':
            if previous is None:
                fail('ai_original_text_use_not_allowed', 404)
            value_hash = previous.payload['text_hash']
            target = previous.payload['recipient']
        else:
            value_hash = digest(excerpt_for(db, payload.selection, {})['text'])
        owner = current_user(db, request.state.session_id)
        value = {'purpose': payload.purpose, 'selection': payload.selection.model_dump(),
            'text_hash': value_hash, 'recipient': target, 'request': payload.model_dump(mode='json')}
        binding = {'scope_hash': scope, 'revision': payload.expected_revision + 1,
            'actor_user_id': owner.id, 'payload': value}
        row = TextEmbeddingAuthorization(**binding, fingerprint=digest(binding))
        db.add(row)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'original_text_authorization_added',
            authorization_id=row.id, revision=row.revision, authorization_action=payload.action, purpose=payload.purpose)
        db.commit()
        return {'purpose': payload.purpose, 'scope_hash': scope, 'authorization': authorization_view(row)}
