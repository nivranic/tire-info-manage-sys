"""Explicit history-only device exports; immutable bytes, independent of AI packs."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import desc, select

from .db import EvidenceObject, uid, utc, utcnow
from .documents import record_object
from .domain import StrictModel, digest
from .field_authority import policy_catalog
from .object_store import ObjectStoreError
from .offline_evidence import document_count, documents, omission, resolve_scope, scope_limit
from .offline_models import OfflinePack, OfflinePackPlan
from .recall_evidence import recall_policy_descriptor
from .service import QueryService, timestamp

CAPACITY = {'version': 'offline-policy@1', 'max_package_bytes': 8 * 1024 * 1024,
    'max_distinct_evidence': 200, 'max_garage_profiles': 50, 'max_watch_items': 100,
    'max_recent_query_candidates': 20, 'max_searchable_documents': 4000,
    'plan_ttl_seconds': 600, 'raw_policy': 'exclude'}
MAX_PREVIEW_BYTES = 32 * 1024 * 1024
MAX_CANONICAL_CACHE_BYTES = 8 * 1024 * 1024
Identifier = Annotated[str, Field(min_length=1, max_length=64)]
Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class CanonicalJSON:
    """stable_json-compatible UTF-8 stream with bounded capture and memoization.

    Shared frozen resolutions are encoded once, then replayed into the hash in
    C-backed byte chunks. No whole over-limit envelope string/bytes is allocated.
    Cache size is independent of selected member count and never exceeds 8MiB.
    """
    def __init__(self, shared=()):
        self.shared = {id(value) for value in shared}
        self.cache, self.uncacheable = {}, set()
        self.cached_bytes = 0
        self.encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

    def chunks(self, value, *, skip_shared=False):
        identity = id(value)
        if not skip_shared and identity in self.shared:
            if identity in self.cache:
                yield self.cache[identity]
                return
            budget = MAX_CANONICAL_CACHE_BYTES - self.cached_bytes
            if budget > 0 and identity not in self.uncacheable:
                capture = bytearray()
                for chunk in self.chunks(value, skip_shared=True):
                    if capture is not None:
                        if len(capture) + len(chunk) <= budget:
                            capture.extend(chunk)
                        else:
                            capture = None
                    yield chunk
                if capture is not None:
                    saved = bytes(capture)
                    self.cache[identity] = saved
                    self.cached_bytes += len(saved)
                else:
                    self.uncacheable.add(identity)
                return
        if isinstance(value, dict):
            yield b'{'
            for index, key in enumerate(sorted(value)):
                if index:
                    yield b','
                yield self.encoder.encode(key).encode('utf-8')
                yield b':'
                yield from self.chunks(value[key])
            yield b'}'
        elif isinstance(value, (list, tuple)):
            yield b'['
            for index, item in enumerate(value):
                if index:
                    yield b','
                yield from self.chunks(item)
            yield b']'
        else:
            yield self.encoder.encode(value).encode('utf-8')

    def measure(self, value, *, capture_limit=0):
        total, hasher = 0, hashlib.sha256()
        capture = bytearray() if capture_limit else None
        for chunk in self.chunks(value):
            total += len(chunk)
            hasher.update(chunk)
            if capture is not None:
                if total <= capture_limit:
                    capture.extend(chunk)
                else:
                    capture = None
        return total, hasher.hexdigest(), bytes(capture) if capture is not None else None


class TireReference(StrictModel):
    kind: Literal['tire']
    snapshot_id: Identifier
    variant_id: Identifier
    verification_id: Identifier | None = None


class VehicleReference(StrictModel):
    kind: Literal['vehicle']
    snapshot_id: Identifier
    verification_id: Identifier | None = None


class RecallReference(StrictModel):
    kind: Literal['recall']
    snapshot_id: Identifier
    recall_revision_id: Identifier | None
    verification_id: Identifier | None = None


class TestReference(StrictModel):
    kind: Literal['test_event']
    event_id: Identifier
    event_revision: StrictInt = Field(ge=1)


class RecallSearchReference(StrictModel):
    kind: Literal['recall_search']
    snapshot_id: Identifier
    verification_id: Identifier


Reference = Annotated[TireReference | VehicleReference | RecallReference | TestReference | RecallSearchReference,
                      Field(discriminator='kind')]
PackSchema = Literal['offline-pack@1', 'offline-pack@2']


class GarageScope(StrictModel):
    include: StrictBool = True
    vehicle_ids: list[Identifier] | None = Field(None, max_length=1000)


class WatchScope(StrictModel):
    include: StrictBool = True
    item_ids: list[Identifier] | None = Field(None, max_length=1000)


class RecentScope(StrictModel):
    include: StrictBool = True
    limit: StrictInt = Field(20, ge=0, le=20)


class OfflineScope(StrictModel):
    garage: GarageScope = Field(default_factory=GarageScope)
    watchlist: WatchScope = Field(default_factory=WatchScope)
    recent: RecentScope = Field(default_factory=RecentScope)
    references: list[Reference] = Field(default_factory=list, max_length=1000)


class NegotiatedPackRequest(StrictModel):
    supported_pack_schemas: list[PackSchema] = Field(default_factory=lambda: ['offline-pack@1'], min_length=1, max_length=2)

    @field_validator('supported_pack_schemas')
    @classmethod
    def unique_schemas(cls, value):
        return list(dict.fromkeys(value))

    @model_validator(mode='after')
    def reference_version(self):
        if ('offline-pack@2' not in self.supported_pack_schemas
                and any(ref.kind == 'recall_search' for ref in self.scope.references)):
            raise ValueError('recall_search 需要显式支持 offline-pack@2')
        return self


class PlanRequest(NegotiatedPackRequest):
    mode: Literal['history']
    scope: OfflineScope = Field(default_factory=OfflineScope)
    base_pack_id: Identifier | None = None


class UpdateRequest(NegotiatedPackRequest):
    mode: Literal['history']
    base_pack_id: Identifier
    expected_base_sha256: Hash
    scope: OfflineScope = Field(default_factory=OfflineScope)


class ConfirmRequest(StrictModel):
    plan_id: Identifier
    expected_fingerprint: Hash
    allow_device_storage: StrictBool

    @field_validator('allow_device_storage')
    @classmethod
    def explicit_storage_consent(cls, value):
        if value is not True:
            raise ValueError('必须明确授权在设备保存此离线包')
        return value


def owned(db, model, identifier, session_id):
    row = db.scalar(select(model).where(model.id == identifier, model.actor_session_id == session_id))
    if row is None:
        raise HTTPException(404, '未找到本会话的离线计划或包')
    return row


def content(db, row):
    try:
        stored = db.get(EvidenceObject, row.content_hash) if row.content_hash else None
        if stored is None or stored.byte_count != row.byte_count:
            raise ObjectStoreError('offline_object_metadata_mismatch')
        return db.info['object_store'].get(row.content_hash, row.byte_count)
    except ObjectStoreError:
        raise HTTPException(503, {'code': 'offline_frozen_object_unavailable'}) from None


@dataclass
class PreparedPlan:
    envelope: dict
    preview: dict
    raw: bytes | None
    created_at: datetime
    writer: CanonicalJSON


def prepare_plan(db, registry, request, session_id, previous=None):
    """Resolve and measure within the caller's lock, without storing any object."""
    supported = request.supported_pack_schemas
    pack_schema = previous['schema'] if previous else ('offline-pack@2' if 'offline-pack@2' in supported else 'offline-pack@1')
    if pack_schema not in supported:
        raise HTTPException(409, {'code': 'offline_pack_schema_not_supported'})
    version = pack_schema.rsplit('@', 1)[1]
    scope = request.scope.model_dump()
    if version == '1' and any(ref['kind'] == 'recall_search' for ref in scope['references']):
        raise HTTPException(422, {'code': 'offline_reference_schema_not_supported'})
    for ref in scope['references']:
        if ref.get('verification_id') is None:
            ref.pop('verification_id', None)
    contexts, members, omissions, counts = resolve_scope(db, registry, scope, session_id, limits=CAPACITY,
                                                       pack_schema=pack_schema)
    scope_limit('searchable_documents', document_count(contexts, members), CAPACITY['max_searchable_documents'])
    docs = documents(contexts, members, preview_byte_limit=MAX_PREVIEW_BYTES)
    counts.update(distinct_evidence=len(members), searchable_documents=len(docs))
    for field, limit in [('garage_profiles', 'max_garage_profiles'), ('watch_items', 'max_watch_items'),
                         ('recent_queries', 'max_recent_query_candidates'), ('distinct_evidence', 'max_distinct_evidence'),
                         ('searchable_documents', 'max_searchable_documents')]:
        scope_limit(field, counts[field], CAPACITY[limit])
    created = utcnow()
    plan_id, package_id = uid(), uid()
    owner_scope = digest({'namespace': 'offline-owner-scope@1', 'session': session_id})
    privacy = 'restricted' if any(item['privacy_class'] == 'restricted' for item in members) else 'private'
    envelope = {'schema': pack_schema, 'package_id': package_id, 'created_at': timestamp(created),
        'owner_scope_id': owner_scope, 'privacy_class': privacy, 'data_state': 'local_snapshot',
        'source_refresh_performed': False, 'base_pack_id': request.base_pack_id, 'scope': scope,
        'contracts': {'offline_policy': CAPACITY['version'], 'field_policy': policy_catalog(),
                      'recall_policy': recall_policy_descriptor()},
        'contexts': contexts, 'members': members, 'documents': docs, 'omissions': omissions}
    writer = CanonicalJSON(item['payload']['field_resolution'] for item in members if item['reference']['kind'] == 'tire')
    _, fingerprint, _ = writer.measure(envelope)
    envelope['plan_fingerprint'] = fingerprint
    measured, content_sha256, raw = writer.measure(envelope, capture_limit=CAPACITY['max_package_bytes'])
    over_bytes = measured > CAPACITY['max_package_bytes']
    # The byte-limit error is preview metadata, not a content rewrite. If blocked
    # there is no object, no partial content and no confirmable package.
    preview_omissions = deepcopy(omissions)
    if over_bytes:
        preview_omissions.append(omission('capacity', None, 'package_bytes_limit_exceeded', True))
    can_confirm = not any(item['blocking'] for item in preview_omissions)
    current = {item['key']: item for item in members}
    old = {item['key']: item for item in previous['members']} if previous else {}
    diff = {'added': sorted(current.keys() - old.keys()), 'removed': sorted(old.keys() - current.keys()),
            'changed': sorted(key for key in current.keys() & old.keys()
                              if writer.measure(current[key])[1] != writer.measure(old[key])[1])}
    preview = {'schema': 'offline-pack-plan@' + version, 'id': plan_id, 'package_id': package_id,
        'state': 'ready' if can_confirm else 'blocked', 'created_at': timestamp(created),
        'expires_at': timestamp(created + timedelta(seconds=CAPACITY['plan_ttl_seconds'])),
        'fingerprint': fingerprint, 'owner_scope_id': owner_scope, 'privacy_class': privacy,
        'requested_scope': scope, 'base_pack_id': request.base_pack_id,
        'resolved': [{key: deepcopy(item[key]) for key in ('key', 'reference', 'member_reasons', 'privacy_class', 'raw_included')}
                     for item in members], 'contexts': deepcopy(contexts), 'documents': deepcopy(docs),
        'omissions': preview_omissions, 'counts': counts,
        'measured_bytes': measured, 'content_sha256': None if over_bytes else content_sha256,
        'capacity': deepcopy(CAPACITY), 'can_confirm': can_confirm,
        'privacy_notice': 'Garage 属于本地工作区；关注项和最近查询属于当前会话。导出包含私人用户上下文。',
        'rights_notice': '仅保存结构化事实和证据短摘录；排除原始全文、图片与链接媒体。保存声明不等于转载许可。',
        'diff': diff}
    preview_bytes, _, _ = writer.measure(preview)
    if preview_bytes > MAX_PREVIEW_BYTES:
        # Never return a misleading empty/trimmed preview to fit the native
        # transport. The user must narrow the exact requested scope first.
        raise HTTPException(413, {'code': 'offline_preview_transport_limit_exceeded',
            'preview_bytes': preview_bytes, 'max_preview_bytes': MAX_PREVIEW_BYTES,
            'action': 'narrow_scope_and_prepare_again'})
    return PreparedPlan(envelope, preview, raw, created, writer)


def persist_plan(db, prepared, session_id):
    preview, raw, created = prepared.preview, prepared.raw, prepared.created_at
    content_hash = None
    if preview['can_confirm']:
        try:
            assert raw is not None
            content_hash = record_object(db, raw)
        except ObjectStoreError:
            raise HTTPException(503, {'code': 'offline_freeze_storage_failed'}) from None
    row = OfflinePackPlan(id=preview['id'], package_id=preview['package_id'], actor_session_id=session_id,
        fingerprint=preview['fingerprint'], preview=preview, content_hash=content_hash, byte_count=preview['measured_bytes'],
        created_at=created, expires_at=created + timedelta(seconds=CAPACITY['plan_ttl_seconds']))
    db.add(row)
    db.commit()
    return deepcopy(preview)


def create_plan(db, registry, request, session_id):
    # One short serialized transaction pins formal receipts and user revisions
    # across selectors. All external providers are outside this code path.
    QueryService(db, None).lock_ingestion()
    previous = None
    if request.base_pack_id:
        previous = json.loads(content(db, owned(db, OfflinePack, request.base_pack_id, session_id)))
    return persist_plan(db, prepare_plan(db, registry, request, session_id, previous), session_id)


SEMANTIC_NAMESPACE = 'offline-semantic@1'
SEMANTIC_NONCES = frozenset({'package_id', 'created_at', 'plan_fingerprint', 'base_pack_id'})
SEMANTIC_REQUIRED = frozenset({'schema', 'owner_scope_id', 'privacy_class', 'data_state',
    'source_refresh_performed', 'scope', 'contracts', 'contexts', 'members', 'documents', 'omissions'})


def semantic_digest(envelope, writer=None):
    """Only top-level export nonces are excluded; nested receipts remain exact."""
    projection = {key: value for key, value in envelope.items() if key not in SEMANTIC_NONCES}
    return (writer or CanonicalJSON()).measure({'namespace': SEMANTIC_NAMESPACE, 'envelope': projection})[1]


def update_base_envelope(db, row, session_id):
    raw = content(db, row)
    try:
        envelope = json.loads(raw)
        descriptor = row.descriptor
        owner_scope = digest({'namespace': 'offline-owner-scope@1', 'session': session_id})
        if (not isinstance(envelope, dict) or not isinstance(descriptor, dict)
                or not SEMANTIC_REQUIRED.issubset(envelope)
                or envelope['schema'] not in {'offline-pack@1', 'offline-pack@2'}
                or descriptor.get('schema') != 'offline-pack-descriptor@' + envelope['schema'].rsplit('@', 1)[1]
                or descriptor.get('id') != row.id or descriptor.get('plan_id') != row.plan_id
                or descriptor.get('sha256') != row.content_hash or descriptor.get('byte_count') != row.byte_count
                or envelope.get('package_id') != row.id
                or envelope.get('plan_fingerprint') != descriptor.get('plan_fingerprint')
                or envelope.get('created_at') != descriptor.get('content_created_at')
                or envelope.get('base_pack_id') != descriptor.get('base_pack_id')
                or envelope['owner_scope_id'] != owner_scope or descriptor.get('owner_scope_id') != owner_scope
                or envelope['privacy_class'] not in {'private', 'restricted'}
                or envelope['privacy_class'] != descriptor.get('privacy_class')
                or envelope['data_state'] != 'local_snapshot' or descriptor.get('data_state') != 'local_snapshot'
                or envelope['source_refresh_performed'] is not False
                or descriptor.get('source_refresh_performed') is not False
                or any(not isinstance(envelope[key], dict) for key in ('scope', 'contracts'))
                or any(not isinstance(envelope[key], list) for key in ('contexts', 'members', 'documents', 'omissions'))):
            raise ValueError('offline_frozen_metadata_mismatch')
        original = {key: value for key, value in envelope.items() if key != 'plan_fingerprint'}
        if CanonicalJSON().measure(original)[1] != envelope['plan_fingerprint']:
            raise ValueError('offline_frozen_fingerprint_mismatch')
        return envelope
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(503, {'code': 'offline_frozen_object_unavailable'}) from None


def prepare_update(db, registry, request, session_id):
    QueryService(db, None).lock_ingestion()
    base = owned(db, OfflinePack, request.base_pack_id, session_id)
    if request.expected_base_sha256 != base.content_hash:
        raise HTTPException(409, {'code': 'offline_base_sha256_mismatch'})
    previous = update_base_envelope(db, base, session_id)
    payload = PlanRequest(mode='history', scope=request.scope, base_pack_id=base.id,
                          supported_pack_schemas=request.supported_pack_schemas)
    prepared = prepare_plan(db, registry, payload, session_id, previous)
    base_digest = semantic_digest(previous)
    current_digest = semantic_digest(prepared.envelope, prepared.writer)
    unchanged = base_digest == current_digest
    # The existing valid base is reusable even if newly generated nonces alone
    # would push a replacement past 8MiB. Scope/complete-preview checks ran above.
    preview = None if unchanged else persist_plan(db, prepared, session_id)
    return {'schema': 'offline-pack-update@' + previous['schema'].rsplit('@', 1)[1], 'state': 'no_change' if unchanged else 'planned',
        'mode': 'history', 'base_pack_id': base.id, 'base_semantic_digest': base_digest,
        'current_semantic_digest': current_digest, 'base_pack': deepcopy(base.descriptor),
        'plan': preview, 'source_refresh_performed': False}


def confirm_plan(db, request, session_id, key):
    try:
        key = str(UUID(key))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'Idempotency-Key 必须为 UUID') from None
    request_hash = digest(request.model_dump())
    QueryService(db, None).lock_ingestion()
    previous = db.scalar(select(OfflinePack).where(OfflinePack.actor_session_id == session_id,
                                                  OfflinePack.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise HTTPException(409, {'code': 'offline_idempotency_payload_mismatch'})
        return deepcopy(previous.descriptor)
    plan = owned(db, OfflinePackPlan, request.plan_id, session_id)
    if plan.fingerprint != request.expected_fingerprint:
        raise HTTPException(409, {'code': 'offline_plan_fingerprint_mismatch'})
    if utc(plan.expires_at) <= utcnow():
        raise HTTPException(409, {'code': 'offline_plan_expired'})
    if not plan.preview['can_confirm'] or not plan.content_hash:
        raise HTTPException(409, {'code': 'offline_plan_blocked'})
    if db.scalar(select(OfflinePack.id).where(OfflinePack.plan_id == plan.id)):
        raise HTTPException(409, {'code': 'offline_plan_already_confirmed'})
    content(db, plan)  # Verify original bytes; never reload current domain evidence.
    created = utcnow()
    preview = plan.preview
    if preview.get('schema') not in {'offline-pack-plan@1', 'offline-pack-plan@2'}:
        raise HTTPException(503, {'code': 'offline_plan_schema_not_supported'})
    descriptor = {'schema': 'offline-pack-descriptor@' + preview['schema'].rsplit('@', 1)[1], 'id': plan.package_id, 'plan_id': plan.id,
        'created_at': timestamp(created), 'content_created_at': preview['created_at'],
        'plan_fingerprint': plan.fingerprint, 'owner_scope_id': preview['owner_scope_id'],
        'privacy_class': preview['privacy_class'], 'sha256': plan.content_hash, 'byte_count': plan.byte_count,
        'base_pack_id': preview['base_pack_id'], 'counts': deepcopy(preview['counts']),
        'download_path': f'/v1/offline-packs/{plan.package_id}/download?mode=history',
        'data_state': 'local_snapshot', 'source_refresh_performed': False}
    db.add(OfflinePack(id=plan.package_id, plan_id=plan.id, actor_session_id=session_id,
        idempotency_key=key, request_hash=request_hash, content_hash=plan.content_hash,
        byte_count=plan.byte_count, descriptor=descriptor, created_at=created))
    db.commit()
    return descriptor


def register_offline_routes(app):
    @app.post('/v1/offline-pack-updates:prepare')
    def prepare_conditional_update(payload: UpdateRequest, request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with app.state.database.sessions() as db:
            return prepare_update(db, app.state.registry, payload, request.state.session_id)

    @app.post('/v1/offline-pack-plans', status_code=201)
    def prepare(payload: PlanRequest, request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with app.state.database.sessions() as db:
            return create_plan(db, app.state.registry, payload, request.state.session_id)

    @app.get('/v1/offline-pack-plans/{plan_id}')
    def get_plan(plan_id: str, request: Request, response: Response, mode: Literal['history'] = Query(...)):
        response.headers['Cache-Control'] = 'no-store'
        with app.state.database.sessions() as db:
            return owned(db, OfflinePackPlan, plan_id, request.state.session_id).preview

    @app.post('/v1/offline-packs', status_code=201)
    def confirm(payload: ConfirmRequest, request: Request, response: Response,
                idempotency_key: str = Header(alias='Idempotency-Key', max_length=64)):
        response.headers['Cache-Control'] = 'no-store'
        with app.state.database.sessions() as db:
            return confirm_plan(db, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/offline-packs')
    def list_packs(request: Request, response: Response, mode: Literal['history'] = Query(...),
                   limit: int = Query(50, ge=1, le=100)):
        from .auth import session_scope
        response.headers['Cache-Control'] = 'no-store'
        with app.state.database.sessions() as db:
            rows = db.scalars(select(OfflinePack).where(OfflinePack.actor_session_id.in_(session_scope(db, request.state.session_id)))
                .order_by(desc(OfflinePack.created_at), desc(OfflinePack.id)).limit(limit)).all()
            return {'items': [row.descriptor for row in rows]}

    @app.get('/v1/offline-packs/{package_id}')
    def get_pack(package_id: str, request: Request, response: Response, mode: Literal['history'] = Query(...)):
        response.headers['Cache-Control'] = 'no-store'
        with app.state.database.sessions() as db:
            return owned(db, OfflinePack, package_id, request.state.session_id).descriptor

    @app.get('/v1/offline-packs/{package_id}/download')
    def download(package_id: str, request: Request, mode: Literal['history'] = Query(...)):
        with app.state.database.sessions() as db:
            row = owned(db, OfflinePack, package_id, request.state.session_id)
            raw = content(db, row)
            headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Content-Length': str(row.byte_count), 'ETag': '"' + row.content_hash + '"',
                'X-Content-SHA256': row.content_hash,
                'Content-Disposition': f'attachment; filename="offline-{row.id}.json"'}
        return StreamingResponse((raw[start:start + 65536] for start in range(0, len(raw), 65536)),
                                 media_type='application/json', headers=headers)
