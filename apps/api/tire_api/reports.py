"""Session-owned frozen research reports and verified derived export downloads."""
from copy import deepcopy
import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi import Header
from pydantic import Field, StrictInt
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, load_only

from .ai_analysis import grounded_answer, owned_pack
from .ai_recall_contract import is_recall_evidence, validate_recall_payload
from .ai_models import AICompletion, AIRequest
from .db import uid
from .domain import StrictModel, digest, stable_json
from .lifecycle import annotate_variants
from .object_store import ObjectStoreError, checked
from .report_models import ReportExport, ResearchReport, ResearchReportRevision
from .research import DescriptionText
from .service import QueryService, timestamp

REPORT_SCHEMA = 'research-report@3'
HISTORY_NOTICE = ('本报告保存的是所选证据包与可选分析的冻结历史副本，不代表当前参数、库存或适配结论。'
                  '模型推断不是来源事实；后续来源变化、撤销或修订不会改写已保存正文。')
FORMATS = {'markdown': ('text/markdown', 'md'), 'html': ('text/html', 'html'), 'pdf': ('application/pdf', 'pdf')}


class ReportCreate(StrictModel):
    mode: Literal['history']
    pack_id: str = Field(min_length=1, max_length=64)
    analysis_id: str | None = Field(default=None, min_length=1, max_length=64)
    title: DescriptionText = Field(min_length=1, max_length=160)
    notes: DescriptionText = Field(default='', max_length=4000)


class ReportEdit(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    title: DescriptionText = Field(min_length=1, max_length=160)
    notes: DescriptionText = Field(default='', max_length=4000)


class ReportState(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal['archive', 'restore']


class ExportRequest(StrictModel):
    revision: StrictInt = Field(ge=1)
    format: Literal['markdown', 'html', 'pdf']


def latest_revision(db, report_id, expected=None):
    row = db.scalar(select(ResearchReportRevision).where(ResearchReportRevision.report_id == report_id)
                    .order_by(desc(ResearchReportRevision.revision)).limit(1))
    if row is None:
        raise HTTPException(409, '报告元数据修订缺失')
    if expected is not None and row.revision != expected:
        raise HTTPException(409, '报告已更新，请重新载入后审核')
    return row


def owned_report(db, report_id, session_id):
    row = db.get(ResearchReport, report_id)
    if row is None or row.actor_session_id != session_id:
        raise HTTPException(404, '未找到本会话的报告')
    if digest(row.body) != row.body_hash:
        raise HTTPException(409, '报告正文完整性校验失败')
    return row


def canonical_facts(payload):
    validate_recall_payload(payload)
    evidence = deepcopy(payload.get('evidence'))
    if not isinstance(evidence, list) or not evidence or len({item['id'] for item in evidence}) != len(evidence):
        raise ValueError('invalid_report_evidence')
    by_id = {item['id']: item for item in evidence}
    facts = deepcopy(payload.get('facts'))
    if not isinstance(facts, list) or len({item['id'] for item in facts}) != len(facts):
        raise ValueError('invalid_report_facts')
    for fact in facts:
        source = by_id[fact['evidence_id']]
        if is_recall_evidence(source):
            # The shared pure validator reconstructs the complete records and
            # compares every field/text, including duplicate record occurrences.
            continue
        value = fact['value']
        if source.get('kind') == 'change_event' and isinstance(value, dict) and fact['field'].endswith('· 冻结差异'):
            if set(value) != {'before', 'after', 'before_present', 'after_present'} or any(
                    type(value[key]) is not bool for key in ('before_present', 'after_present')):
                raise ValueError('invalid_report_change')
            def side(name):
                return '未声明此字段' if not value[name + '_present'] else '明确未知（null）' if value[name] is None else stable_json(value[name])
            rendered = f'{source["label"]}：{fact["field"]}，{side("before")} → {side("after")}'
        else:
            display = '来源未标明' if value is None else '是' if value is True else '否' if value is False else value if isinstance(value, str) else stable_json(value)
            rendered = f'{source["label"]}：{fact["field"]} = {display}'
        fact['text'] = rendered
    return evidence, facts


def freeze_body(db, pack, analysis_id, session_id):
    if pack.payload.get('purpose') == 'rule_draft':
        raise HTTPException(422, '规则草稿不能保存为研究事实报告')
    try:
        evidence, facts = canonical_facts(pack.payload)
        from .ai_evidence import frozen_field_resolutions
        field_contract = {}
        if 'field_resolutions' in pack.payload:
            field_contract['field_resolutions'] = frozen_field_resolutions(pack.payload)
        if 'field_policy' in pack.payload:
            field_contract['field_policy'] = deepcopy(pack.payload['field_policy'])
        if validate_recall_payload(pack.payload):
            from .recall_evidence import load_recall_evidence
            for item in evidence:
                if is_recall_evidence(item):
                    frozen = load_recall_evidence(db, item['snapshot_id'], item['recall_revision_id'],
                                                  verification_id=item['verification_id'])
                    if any(item.get(key) != value for key, value in frozen['evidence'].items()):
                        raise ValueError('invalid_report_recall_binding')
            field_contract['recall_policy'] = deepcopy(pack.payload['recall_policy'])
            field_contract['recall_boundary'] = deepcopy(pack.payload['recall_boundary'])
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, '证据包引用结构无效，不能保存报告') from None
    ids = list({item['variant_id'] for item in evidence if item.get('variant_id')})
    if any(item['lifecycle']['state'] == 'revoked' for item in annotate_variants(db, [{'id': value} for value in ids])):
        raise HTTPException(409, '所选精确版本已撤销，请重新核对后保存')
    from .test_events import latest
    for item in evidence:
        if item.get('event_id'):
            current = latest(db, item['event_id'], item['revision'])
            if current.state == 'revoked':
                raise HTTPException(409, '所选测试事件已撤销')
    analysis = None
    if analysis_id:
        row = db.get(AIRequest, analysis_id)
        if row is None or row.actor_session_id != session_id:
            raise HTTPException(404, '未找到本会话的分析')
        completion = db.get(AICompletion, row.id)
        if (row.pack_id != pack.id or row.request_contract.get('purpose') == 'rule_draft'
                or not completion or completion.state != 'completed' or not completion.answer):
            raise HTTPException(409, '请选择同一证据包已完成的研究分析')
        # Stored presentation text is not authority. Re-run citation validation
        # and render fact claims using reconstructed canonical fact values.
        answer = completion.answer
        try:
            claims = [{key: item[key] for key in ('type', 'text', 'fact_ids', 'evidence_ids')} for item in answer['claims']]
            for claim in claims:
                if claim['type'] == 'fact':
                    claim['text'] = ''
            from types import SimpleNamespace
            canonical = SimpleNamespace(payload={**pack.payload, 'evidence': evidence, 'facts': facts}, data_state=pack.data_state)
            validated = grounded_answer(json.dumps({'claims': claims, 'uncertainty': answer['uncertainty']}), canonical)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(409, '分析的事实或证据引用无效，未保存报告') from None
        analysis = {'id': row.id, 'question': row.question, 'provider': row.provider, 'model': row.model,
            'created_at': timestamp(row.created_at), 'completed_at': timestamp(completion.created_at),
            'usage': completion.usage, 'claims': validated['claims'], 'uncertainty': validated['uncertainty']}
    return {'data_state': 'local_snapshot', 'source_pack': {'id': pack.id, 'fingerprint': pack.fingerprint,
        'mode': pack.mode, 'data_state': pack.data_state, 'privacy_class': pack.privacy_class,
        'created_at': timestamp(pack.created_at), 'expires_at': timestamp(pack.expires_at)},
        'privacy_class': 'private', 'evidence': evidence, 'facts': facts,
        'conflicts': deepcopy(pack.payload.get('conflicts', [])), 'analysis': analysis, 'notice': HISTORY_NOTICE,
        **field_contract}


def revision_view(row):
    return {'revision': row.revision, 'title': row.title, 'notes': row.notes, 'archived': row.archived,
            'operation': row.operation, 'created_at': timestamp(row.created_at)}


def metadata(report, revision):
    return {'id': report.id, 'title': revision.title, 'notes': revision.notes, 'revision': revision.revision,
            'archived': revision.archived, 'created_at': timestamp(report.created_at), 'updated_at': timestamp(revision.created_at),
            'body_hash': report.body_hash, 'privacy_class': report.privacy_class, 'pack_id': report.pack_id,
            'analysis_id': report.analysis_id, 'data_state': 'local_snapshot'}


def export_view(row):
    return {key: getattr(row, key) for key in ('id', 'report_id', 'revision', 'format', 'renderer_version', 'content_type', 'byte_count', 'sha256')} | {
        'created_at': timestamp(row.created_at),
        'content_url': f'/v1/reports/{row.report_id}/exports/{row.id}/content?mode=history&revision={row.revision}'}


def detail(db, report, revision=None):
    revision = revision or latest_revision(db, report.id)
    history = db.scalars(select(ResearchReportRevision).where(ResearchReportRevision.report_id == report.id)
                        .order_by(desc(ResearchReportRevision.revision)).limit(51)).all()
    exports = db.scalars(select(ReportExport).where(ReportExport.report_id == report.id)
                        .order_by(desc(ReportExport.created_at)).limit(100)).all()
    ids = {item['variant_id'] for item in report.body['evidence'] if item.get('variant_id')}
    states = annotate_variants(db, [{'id': value} for value in sorted(ids)])
    return {**metadata(report, revision), 'scope': 'browser_session', 'body': report.body,
        'metadata_history': [revision_view(row) for row in history[:50]], 'history_truncated': len(history) > 50,
        'exports': [export_view(row) for row in exports], 'current_lifecycle': [
            {'variant_id': row['id'], 'state': row['lifecycle']['state'], 'revision': row['lifecycle']['revision']} for row in states]}


def document_for(report, revision):
    return {'schema_version': REPORT_SCHEMA, 'report_id': report.id, 'title': revision.title, 'notes': revision.notes,
            'revision': revision.revision, 'created_at': timestamp(report.created_at), 'body': report.body}


def report_revision(db, report_id, revision):
    row = db.scalar(select(ResearchReportRevision).where(ResearchReportRevision.report_id == report_id,
                                                         ResearchReportRevision.revision == revision))
    if row is None:
        raise HTTPException(404, '未找到所选报告修订')
    return row


def register_report_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/reports', status_code=201)
    def create(payload: ReportCreate, request: Request, idempotency_key: str = Header(alias='Idempotency-Key', max_length=64),
               db: Session = Depends(get_db)):
        try:
            key = str(UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422, 'Idempotency-Key 必须是 UUID') from None
        QueryService(db, None).lock_ingestion()
        request_hash = digest(payload.model_dump())
        previous = db.scalar(select(ResearchReport).where(ResearchReport.actor_session_id == request.state.session_id,
                                                         ResearchReport.idempotency_key == key))
        if previous:
            if previous.request_hash != request_hash:
                raise HTTPException(409, '同一幂等键不能用于不同报告内容')
            owned_report(db, previous.id, request.state.session_id)
            result = detail(db, previous)
            db.commit()
            return result
        pack = owned_pack(db, payload.pack_id, request.state.session_id)
        body = freeze_body(db, pack, payload.analysis_id, request.state.session_id)
        row = ResearchReport(id=uid(), actor_session_id=request.state.session_id, idempotency_key=key, request_hash=request_hash,
            pack_id=pack.id, analysis_id=payload.analysis_id, privacy_class='private', body=body, body_hash=digest(body))
        db.add(row)
        db.flush()
        revision = ResearchReportRevision(report_id=row.id, revision=1, title=payload.title, notes=payload.notes, archived=False, operation='create')
        db.add(revision)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'research_report_created', report_id=row.id,
                                   pack_id=pack.id, analysis_id=payload.analysis_id, body_hash=row.body_hash)
        db.commit()
        return detail(db, row, revision)

    @app.get('/v1/reports')
    def listing(request: Request, mode: Literal['history'] = Query(...), archived: bool = False,
                offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
        heads = select(ResearchReportRevision.report_id, func.max(ResearchReportRevision.revision).label('revision')).group_by(
            ResearchReportRevision.report_id).subquery()
        statement = select(ResearchReport, ResearchReportRevision).join(ResearchReportRevision,
            ResearchReportRevision.report_id == ResearchReport.id).join(heads,
            (heads.c.report_id == ResearchReport.id) & (heads.c.revision == ResearchReportRevision.revision)).where(
                ResearchReport.actor_session_id == request.state.session_id, ResearchReportRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.options(load_only(*[getattr(ResearchReport, column.name)
            for column in ResearchReport.__table__.columns if column.name != 'body']))
            .order_by(desc(ResearchReport.created_at), ResearchReport.id).offset(offset).limit(50)).all()
        return {'scope': 'browser_session', 'data_state': 'local_snapshot', 'items': [metadata(row, rev) for row, rev in rows],
                'total': total, 'offset': offset}

    @app.get('/v1/reports/{report_id}')
    def read(report_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        return detail(db, owned_report(db, report_id, request.state.session_id))

    @app.put('/v1/reports/{report_id}')
    def edit(report_id: str, payload: ReportEdit, request: Request, db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        row = owned_report(db, report_id, request.state.session_id)
        current = latest_revision(db, report_id, payload.expected_revision)
        if current.archived:
            raise HTTPException(409, '请先恢复已归档报告')
        if current.title == payload.title and current.notes == payload.notes:
            result = detail(db, row, current)
            db.commit()
            return result
        revision = ResearchReportRevision(report_id=report_id, revision=current.revision + 1, title=payload.title,
            notes=payload.notes, archived=False, operation='edit')
        db.add(revision)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'research_report_metadata_edited', report_id=report_id, revision=revision.revision)
        db.commit()
        return detail(db, row, revision)

    @app.post('/v1/reports/{report_id}/state')
    def state(report_id: str, payload: ReportState, request: Request, db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        row = owned_report(db, report_id, request.state.session_id)
        current = latest_revision(db, report_id, payload.expected_revision)
        archived = payload.action == 'archive'
        if current.archived == archived:
            raise HTTPException(409, '报告已处于所选状态')
        revision = ResearchReportRevision(report_id=report_id, revision=current.revision + 1, title=current.title,
            notes=current.notes, archived=archived, operation=payload.action)
        db.add(revision)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'research_report_state_changed', report_id=report_id, revision=revision.revision)
        db.commit()
        return detail(db, row, revision)

    @app.post('/v1/reports/{report_id}/exports', status_code=201)
    def export(report_id: str, payload: ExportRequest, request: Request, db: Session = Depends(get_db)):
        from .report_rendering import RENDERER_VERSION, ReportRenderError, render_report
        report = owned_report(db, report_id, request.state.session_id)
        revision = report_revision(db, report_id, payload.revision)
        document = document_for(report, revision)
        document_hash = digest(document)
        existing = db.scalar(select(ReportExport).where(ReportExport.report_id == report_id,
            ReportExport.revision == payload.revision, ReportExport.format == payload.format, ReportExport.renderer_version == RENDERER_VERSION))
        if existing:
            if existing.document_hash != document_hash:
                raise HTTPException(409, '导出绑定的修订内容不一致')
            return export_view(existing)
        db.commit()  # Rendering and storage may be slow; never hold an ingestion lock.
        try:
            data = render_report(document, payload.format)
            sha256 = db.info['object_store'].put(data)
            checked(data, sha256, len(data))
        except ReportRenderError:
            raise HTTPException(422, '报告暂时无法导出，请核对正文与导出格式') from None
        except ObjectStoreError:
            raise HTTPException(503, '导出文件存储未完成，未创建导出记录') from None
        QueryService(db, None).lock_ingestion()
        owned_report(db, report_id, request.state.session_id)
        # Concurrent identical exports reuse the first immutable object receipt.
        existing = db.scalar(select(ReportExport).where(ReportExport.report_id == report_id,
            ReportExport.revision == payload.revision, ReportExport.format == payload.format, ReportExport.renderer_version == RENDERER_VERSION))
        if existing:
            if existing.document_hash != document_hash:
                raise HTTPException(409, '导出绑定的修订内容不一致')
            result = export_view(existing)
            db.commit()
            return result
        record = ReportExport(report_id=report_id, revision=payload.revision, format=payload.format,
            renderer_version=RENDERER_VERSION, document_hash=document_hash, content_type=FORMATS[payload.format][0],
            sha256=sha256, byte_count=len(data))
        db.add(record)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'research_report_exported', report_id=report_id,
                                   export_id=record.id, revision=record.revision, sha256=sha256)
        db.commit()
        return export_view(record)

    @app.get('/v1/reports/{report_id}/exports/{export_id}/content')
    def content(report_id: str, export_id: str, request: Request, mode: Literal['history'] = Query(...),
                revision: int = Query(..., ge=1), db: Session = Depends(get_db)):
        report = owned_report(db, report_id, request.state.session_id)
        record = db.get(ReportExport, export_id)
        if record is None or record.report_id != report_id or record.revision != revision:
            raise HTTPException(404, '未找到所选报告修订的导出文件')
        metadata_revision = report_revision(db, report_id, revision)
        if digest(document_for(report, metadata_revision)) != record.document_hash:
            raise HTTPException(409, '导出与冻结报告修订的绑定校验失败')
        try:
            data = checked(db.info['object_store'].get(record.sha256, record.byte_count), record.sha256, record.byte_count)
        except ObjectStoreError:
            raise HTTPException(503, '导出文件缺失或完整性校验失败，未返回内容') from None
        QueryService(db, None).audit(request.state.session_id, 'research_report_downloaded', report_id=report_id,
                                   export_id=record.id, revision=revision, sha256=record.sha256)
        db.commit()
        extension = FORMATS[record.format][1]
        return Response(data, media_type=record.content_type, headers={
            'Content-Disposition': f'attachment; filename="report-{report.id}-r{revision}.{extension}"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'", 'X-Report-SHA256': record.sha256})
