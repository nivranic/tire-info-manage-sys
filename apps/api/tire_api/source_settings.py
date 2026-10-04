"""Local acquisition preferences over fixed code registrations; history stays readable."""
from copy import deepcopy
import os
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictInt, field_validator, model_validator
from sqlalchemy import desc, func, select

from .auth import make_admin_guard
from .domain import StrictModel, digest
from .source_setting_models import SourceSettingRevision

SCOPE = 'local_workspace'
NOTICE = ('仅管理本机数据库工作区的在线采集；不修改来源证据、权威、URL或Parser。'
          '历史读取和无数据库绑定的独立诊断不受此设置控制。启用不能解除环境、来源能力或Parser限制。')
MESSAGES = {
    'source_setting_not_found': '未找到已登记的来源',
    'source_setting_revision_conflict': '来源设置已变化，请重新预览',
    'source_setting_preview_stale': '来源能力或预览内容已变化，请重新预览',
    'source_setting_no_changes': '设置没有变化，不追加修订',
    'source_setting_restore_required': '来源已归档，请先恢复为暂停状态',
    'source_setting_not_archived': '只有已归档来源可以恢复',
    'invalid_idempotency_key': '请提供固定 UUID 请求标识',
    'idempotency_payload_mismatch': '同一 UUID 已绑定不同的来源操作',
    'source_setting_integrity_failed': '来源管理历史完整性校验失败',
    'source_paused': '此来源已在本机暂停在线采集',
    'source_archived': '此来源已在本机归档',
    'source_access_changed': '请求开始后来源采集设置已变化，请重新发起请求',
    'source_access_pin_missing': '旧请求没有来源采集授权代次，请重新发起请求',
}


class SourceSettingError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status, self.status_code = code, status, status


class SourceAccessBlocked(SourceSettingError):
    """Management-only fence; native Adapter and Parser gates remain independent."""


class SourceSettingPreview(StrictModel):
    action: Literal['enable', 'pause', 'archive', 'restore', 'edit_notes']
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator('notes')
    @classmethod
    def plain_notes(cls, value):
        if value is not None:
            _plain_text(value)
        return value

    @model_validator(mode='after')
    def notes_scope(self):
        if self.action == 'edit_notes' and self.notes is None:
            raise ValueError('编辑备注必须显式提供字符串，可用空字符串清空')
        if self.action != 'edit_notes' and self.notes is not None:
            raise ValueError('状态操作不能同时修改备注')
        return self


class SourceSettingDecision(SourceSettingPreview):
    expected_revision: StrictInt = Field(ge=0)
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator('operator', 'reason')
    @classmethod
    def meaningful(cls, value):
        _plain_text(value)
        return value


def _plain_text(value):
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ValueError('文本包含无效字符') from None
    if any(ord(char) < 32 and char not in '\n\t' or ord(char) == 127 for char in value):
        raise ValueError('文本不能包含控制字符')


def _stamp(value):
    from .db import utc
    return utc(value).isoformat() if value else None


def _event_hash(row):
    return digest({key: getattr(row, key) for key in (
        'id', 'source_id', 'revision', 'action', 'state', 'notes', 'access_generation', 'before', 'after',
        'catalog_fingerprint', 'preview_fingerprint', 'operator', 'reason',
        'actor_session_id', 'idempotency_key', 'request_hash')})


def _checked(row):
    if row is not None and row.fingerprint != _event_hash(row):
        raise SourceSettingError('source_setting_integrity_failed', 503)
    return row


def current_setting(db, source_id):
    """Read management only. Callers validate source registration independently.

    Unknown-but-caller-validated fixture/source IDs share virtual enabled/0;
    this helper neither opens a source nor consults the executable catalog.
    """
    row = _checked(db.scalar(select(SourceSettingRevision).where(SourceSettingRevision.source_id == source_id)
        .order_by(desc(SourceSettingRevision.revision)).limit(1).execution_options(populate_existing=True)))
    return {'revision': row.revision if row else 0, 'state': row.state if row else 'enabled',
        'notes': row.notes if row else '', 'access_generation': row.access_generation if row else 0,
        'event_id': row.id if row else None, 'operator': row.operator if row else None,
        'reason': row.reason if row else None, 'changed_at': _stamp(row.created_at) if row else None}


def assert_source_access(db, source_id, expected_generation=None, *, registry=None):
    """Caller owns its transaction/lock. Never commit, lock, or replace native gates.

    None is only for a new request acquiring its current management generation.
    Use assert_source_run_access for old requests/consents so legacy NULL fails.
    Native capabilities, environment disabling and Parser failures retain their
    existing stricter checks and fallback semantics outside this management fence.
    """
    setting = current_setting(db, source_id)
    if expected_generation is not None and (type(expected_generation) is not int
            or expected_generation != setting['access_generation']):
        raise SourceAccessBlocked('source_access_changed')
    if setting['state'] != 'enabled':
        raise SourceAccessBlocked('source_archived' if setting['state'] == 'archived' else 'source_paused')
    return setting['access_generation']


def assert_source_run_access(db, run, *, registry=None):
    if run.source_access_generation is None:
        raise SourceAccessBlocked('source_access_pin_missing')
    return assert_source_access(db, run.source_id, run.source_access_generation, registry=registry)


def _catalog(registry=None):
    if registry is None:
        from .adapters import registry
    from .adapters import xiaomi
    values = {row['id']: deepcopy(row) for row in registry.sources()}
    # The registry already contains tire and recall entries. Vehicle candidates
    # are separate entities; the management key is their shared source ID.
    values[xiaomi.SOURCE_ID] = {'id': xiaomi.SOURCE_ID, 'name': '小米汽车 · 中国官方车型配置',
        'region': 'CN', 'source_class': 'oem_fitment', 'target_kind': 'vehicle', 'status': 'ready',
        'homepage': xiaomi.SOURCE_PAGE, 'supported_models': ['SU7（新一代）'],
        'parser_version': xiaomi.PARSER_VERSION,
        'description': '当前官方车型配置来源；首代候选仍须独立核验，不由来源启用推定可用。'}
    specs = getattr(registry, 'SPECS', {})
    pending = {row['id']: row for row in getattr(registry, 'PENDING_SOURCES', [])}
    disabled = {value.strip() for value in os.getenv('TI_DISABLED_SOURCES', '').split(',') if value.strip()}
    for source_id, row in values.items():
        if source_id in specs:
            native_status = specs[source_id].status
        elif source_id in pending:
            native_status = pending[source_id]['status']
        elif source_id == 'nhtsa-us-recalls' and getattr(registry, 'supports_parser_deployments', False) is True:
            native_status = 'ready'
        else:
            native_status = row.get('status', 'not_implemented')
        row['registered_status'] = native_status
        row['environment_disabled'] = source_id in disabled
        row.setdefault('target_kind', 'tire')
    return values


def _effective(registered, management, deployment):
    blockers = []
    if management['state'] == 'archived':
        blockers.append('source_archived')
    elif management['state'] == 'paused':
        blockers.append('source_paused')
    if registered['environment_disabled']:
        blockers.append('source_environment_disabled')
    if registered['registered_status'] != 'ready':
        blockers.append(registered['registered_status'])
    if deployment and deployment['state'] != 'active':
        blockers.append('parser_deployment_paused')
    status = ('archived' if management['state'] == 'archived' else
              'paused' if management['state'] == 'paused' else
              'disabled' if registered['environment_disabled'] else
              registered['registered_status'] if registered['registered_status'] != 'ready' else
              'parser_paused' if deployment and deployment['state'] != 'active' else 'ready')
    return {'effective_status': status, 'can_fetch': not blockers, 'blockers': blockers}


def source_setting(db, source_id, *, registry=None):
    registered = _catalog(registry).get(source_id)
    if registered is None:
        raise SourceSettingError('source_setting_not_found', 404)
    from .parser_releases import current_deployment
    row = current_deployment(db, source_id)
    deployment = None if row is None else {'revision': row.revision, 'state': row.state,
        'bundle_id': row.bundle_id, 'parser_version': row.descriptor['parser_version'],
        'parser_digest': row.descriptor['parser_digest']}
    management = current_setting(db, source_id)
    value = {'scope': SCOPE, 'source_id': source_id,
        **{key: registered.get(key) for key in ('name', 'region', 'target_kind', 'source_class', 'homepage')},
        'description': registered.get('description', ''), 'supported_models': registered.get('supported_models', []),
        'registered_status': registered['registered_status'], 'environment_disabled': registered['environment_disabled'],
        'management': management, 'parser_deployment': deployment,
        **_effective(registered, management, deployment), 'notice': NOTICE}
    # Include trusted source capabilities in optimistic validation without making
    # any of them writable. No page body, FTS projection or network is read here.
    fingerprint = digest({'source': value, 'registration': registered})
    return {**value, 'fingerprint': fingerprint}


def _state(management):
    return {key: management[key] for key in ('state', 'notes', 'access_generation')}


def preview_source_setting(db, source_id, payload, *, registry=None):
    source = source_setting(db, source_id, registry=registry)
    before = _state(source['management'])
    after = deepcopy(before)
    blockers = []
    if payload.action == 'edit_notes':
        after['notes'] = payload.notes
    elif payload.action == 'restore':
        if before['state'] != 'archived':
            blockers.append('source_setting_not_archived')
        else:
            after['state'] = 'paused'
    elif before['state'] == 'archived' and payload.action != 'archive':
        blockers.append('source_setting_restore_required')
    else:
        after['state'] = {'enable': 'enabled', 'pause': 'paused', 'archive': 'archived'}[payload.action]
    if after['state'] != before['state']:
        after['access_generation'] += 1
    if after == before and not blockers:
        blockers.append('source_setting_no_changes')
    fingerprint = digest({'source_fingerprint': source['fingerprint'], 'action': payload.action,
                          'before': before, 'after': after})
    return {'scope': SCOPE, 'source_id': source_id, 'action': payload.action,
        'revision': source['management']['revision'], 'fingerprint': fingerprint,
        'before': before, 'after': after, 'can_submit': not blockers, 'blockers': blockers,
        'source': source, 'effective_after': _effective(source, after, source['parser_deployment']), 'notice': NOTICE}


def event_view(row):
    _checked(row)
    return {key: deepcopy(getattr(row, key)) for key in ('id', 'source_id', 'revision', 'action', 'state',
        'notes', 'access_generation', 'before', 'after', 'operator', 'reason', 'idempotency_key', 'fingerprint')} | {
        'created_at': _stamp(row.created_at)}


def append_source_setting(db, source_id, payload, session_id, idempotency_key, *, registry=None):
    try:
        key = str(UUID(idempotency_key))
    except (ValueError, TypeError, AttributeError):
        raise SourceSettingError('invalid_idempotency_key', 422) from None
    from .db import uid
    from .service import QueryService
    shared = QueryService(db, None)
    shared.lock_ingestion()
    request_hash = digest({'source_id': source_id, 'payload': payload.model_dump(mode='json')})
    replay = db.scalar(select(SourceSettingRevision).where(SourceSettingRevision.actor_session_id == session_id,
        SourceSettingRevision.idempotency_key == key))
    if replay:
        if replay.request_hash != request_hash:
            raise SourceSettingError('idempotency_payload_mismatch')
        result = {'source': source_setting(db, source_id, registry=registry), 'event': event_view(replay), 'replayed': True}
        db.commit()
        return result
    proposed = preview_source_setting(db, source_id, payload, registry=registry)
    if proposed['revision'] != payload.expected_revision:
        raise SourceSettingError('source_setting_revision_conflict')
    if proposed['fingerprint'] != payload.expected_fingerprint:
        raise SourceSettingError('source_setting_preview_stale')
    if not proposed['can_submit']:
        raise SourceSettingError(proposed['blockers'][0])
    row = SourceSettingRevision(id=uid(), source_id=source_id, revision=proposed['revision'] + 1,
        action=payload.action, **proposed['after'], before=proposed['before'], after=proposed['after'],
        catalog_fingerprint=proposed['source']['fingerprint'], preview_fingerprint=proposed['fingerprint'],
        operator=payload.operator, reason=payload.reason, actor_session_id=session_id,
        idempotency_key=key, request_hash=request_hash)
    row.fingerprint = _event_hash(row)
    db.add(row)
    db.flush()
    shared.audit(session_id, 'source_setting_changed', source_id=source_id, event_id=row.id,
                 revision=row.revision, action_kind=row.action, access_generation=row.access_generation)
    db.commit()
    return {'source': source_setting(db, source_id, registry=registry), 'event': event_view(row), 'replayed': False}


def register_source_setting_routes(app: FastAPI):
    @app.exception_handler(SourceSettingError)
    async def source_setting_error(_request, error):
        return JSONResponse(status_code=error.status_code,
            content={'detail': {'code': error.code, 'message': MESSAGES.get(error.code, error.code)}})

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/source-settings')
    def listing(db=Depends(get_db)):
        values = [source_setting(db, source_id, registry=app.state.registry) for source_id in sorted(_catalog(app.state.registry))]
        return {'scope': SCOPE, 'items': values, 'total': len(values), 'notice': NOTICE}

    @app.get('/v1/source-settings/{source_id}')
    def detail(source_id: str, db=Depends(get_db)):
        return source_setting(db, source_id, registry=app.state.registry)

    @app.get('/v1/source-settings/{source_id}/history')
    def history(source_id: str, offset: int = Query(0, ge=0, le=100000),
                limit: int = Query(20, ge=1, le=100), db=Depends(get_db)):
        source_setting(db, source_id, registry=app.state.registry)
        statement = select(SourceSettingRevision).where(SourceSettingRevision.source_id == source_id)
        total = db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = db.scalars(statement.order_by(desc(SourceSettingRevision.revision)).offset(offset).limit(limit)).all()
        return {'scope': SCOPE, 'source_id': source_id, 'items': [event_view(row) for row in rows],
                'offset': offset, 'limit': limit, 'total': total}

    @app.post('/v1/source-settings/{source_id}/preview')
    def preview(source_id: str, payload: SourceSettingPreview, db=Depends(get_db)):
        return preview_source_setting(db, source_id, payload, registry=app.state.registry)

    @app.post('/v1/source-settings/{source_id}/revisions', status_code=201, dependencies=[Depends(admin_guard)])
    def revise(source_id: str, payload: SourceSettingDecision, request: Request,
               idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return append_source_setting(db, source_id, payload, request.state.session_id,
                                     idempotency_key, registry=app.state.registry)
