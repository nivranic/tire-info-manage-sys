"""Deterministic, offline exports of a frozen research-report document.

All formats consume the same semantic blocks. Source text is always data: no
HTML interpreter, Markdown-to-HTML converter, browser, or URL fetcher is used.
"""
from dataclasses import dataclass
import base64
import hashlib
import html
from io import BytesIO
import json
from pathlib import Path
import re
from threading import RLock
from urllib.parse import quote, urlsplit

from .object_store import MAX_OBJECT_BYTES

RENDERER_VERSION = 'frozen-research-export@4'
FORMATS = ('markdown', 'html', 'pdf')
_FONT_NAME = 'TireEvidenceSC-Regular'
_FONT_FILE = Path(__file__).resolve().parent / 'assets' / 'fonts' / 'TireEvidenceSC-Regular.ttf'
_FONT_SHA256 = 'fd9a4860d54eda9898638c275636ef45aad5dd04d83998269861a060d64910e3'
_FONT_LOCK = RLock()
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
_MD_SPECIAL = re.compile(r'([\\`*_{}\[\]()#+.!|>~-])')
_STYLE = '''body{font-family:system-ui,"Noto Sans SC","Microsoft YaHei",sans-serif;line-height:1.65;color:#172b35;background:#fff;max-width:900px;margin:40px auto;padding:0 24px}h1{font-size:2rem;line-height:1.3}h2{border-top:1px solid #cbd5da;padding-top:22px;margin-top:32px}h3{font-size:1.05rem;margin-bottom:8px}p{white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:.88rem;border-left:3px solid #8ca3af;padding:8px 14px;background:#f4f7f8}a{color:#165d88;overflow-wrap:anywhere}.meta{color:#48606b;font-size:.9rem}.links{font-size:.9rem}footer{margin-top:36px;border-top:1px solid #cbd5da;padding-top:16px;color:#48606b}@media print{body{max-width:none;margin:0;padding:0}h1,h2,h3{break-after:avoid}pre,p{orphans:3;widows:3}a{color:inherit}}'''


class ReportRenderError(ValueError):
    """Stable error codes only; never return local paths or library diagnostics."""


@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    anchor: str | None = None
    links: tuple[tuple[str, str], ...] = ()
    group: str | None = None


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ReportRenderError('invalid_document') from None


def _text(value, *, empty=True):
    if not isinstance(value, str) or (not empty and not value):
        raise ReportRenderError('invalid_document')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ReportRenderError('invalid_document') from None
    if any(ord(char) < 32 and char not in '\r\n\t' for char in value):
        raise ReportRenderError('invalid_document')
    return value.replace('\r\n', '\n').replace('\r', '\n')


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ReportRenderError('invalid_document')
    return value


def _validate(document):
    if not isinstance(document, dict) or document.get('schema_version') not in {
            'research-report@1', 'research-report@2', 'research-report@3'}:
        raise ReportRenderError('invalid_document')
    for key in ('report_id', 'title', 'created_at'):
        _text(document.get(key), empty=False)
    _text(document.get('notes', ''))
    if type(document.get('revision')) is not int or document['revision'] < 1:
        raise ReportRenderError('invalid_document')
    body = document.get('body')
    if (not isinstance(body, dict) or body.get('data_state') != 'local_snapshot'
            or body.get('privacy_class') not in {'public', 'private', 'restricted'}
            or not isinstance(body.get('source_pack'), dict)):
        raise ReportRenderError('invalid_document')
    evidence, facts = body.get('evidence'), body.get('facts')
    if not isinstance(evidence, list) or not evidence or not isinstance(facts, list) or not facts:
        raise ReportRenderError('invalid_document')
    evidence_by_id, facts_by_id = {}, {}
    for item in evidence:
        if not isinstance(item, dict):
            raise ReportRenderError('invalid_document')
        key = _identifier(item.get('id'))
        if key in evidence_by_id:
            raise ReportRenderError('invalid_document')
        _text(item.get('label'), empty=False)
        evidence_by_id[key] = item
    for item in facts:
        if not isinstance(item, dict):
            raise ReportRenderError('invalid_document')
        key = _identifier(item.get('id'))
        if key in facts_by_id or item.get('evidence_id') not in evidence_by_id or 'value' not in item:
            raise ReportRenderError('unbound_report_citation')
        _text(item.get('field'), empty=False)
        _text(item.get('text'), empty=False)
        facts_by_id[key] = item
    if not isinstance(body.get('conflicts'), list):
        raise ReportRenderError('invalid_document')
    try:
        from .ai_recall_contract import validate_recall_payload
        recall = validate_recall_payload(body, require_purpose=False, frozen=True)
        if recall and document['schema_version'] != 'research-report@3':
            raise ValueError('invalid_recall_schema')
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ReportRenderError('invalid_report_recall_contract') from None
    if 'field_resolutions' in body:
        from .domain import digest
        resolutions = body['field_resolutions']
        if not isinstance(resolutions, list) or not isinstance(body.get('field_policy'), dict):
            raise ReportRenderError('invalid_document')
        for resolution in resolutions:
            if (not isinstance(resolution, dict) or resolution.get('policy') != body['field_policy']
                    or resolution.get('fingerprint') != digest({key: value for key, value in resolution.items() if key != 'fingerprint'})):
                raise ReportRenderError('invalid_document')
            for field in resolution['fields']:
                for candidate in field['candidates']:
                    evidence_id = candidate.get('evidence_id')
                    if (evidence_id not in evidence_by_id
                            or any(key not in facts_by_id or facts_by_id[key]['evidence_id'] != evidence_id
                                   for key in candidate.get('fact_ids', []))):
                        raise ReportRenderError('unbound_report_citation')
    analysis = body.get('analysis')
    if analysis is not None:
        if not isinstance(analysis, dict) or not isinstance(analysis.get('claims'), list):
            raise ReportRenderError('invalid_document')
        for claim in analysis['claims']:
            if not isinstance(claim, dict) or claim.get('type') not in {'fact', 'inference'}:
                raise ReportRenderError('invalid_document')
            _text(claim.get('text'), empty=False)
            field_ids, source_ids = claim.get('fact_ids'), claim.get('evidence_ids')
            if (not isinstance(field_ids, list) or not field_ids or not isinstance(source_ids, list) or not source_ids
                    or any(not isinstance(key, str) for key in field_ids + source_ids)
                    or len(set(field_ids)) != len(field_ids) or len(set(source_ids)) != len(source_ids)
                    or not set(field_ids) <= facts_by_id.keys()
                    or set(source_ids) != {facts_by_id[key]['evidence_id'] for key in field_ids}):
                raise ReportRenderError('unbound_report_citation')
            if claim['type'] == 'fact' and claim['text'] != '\n'.join(facts_by_id[key]['text'] for key in field_ids):
                raise ReportRenderError('unbound_report_citation')
            if recall:
                try:
                    from types import SimpleNamespace
                    from .ai_recall_contract import validate_recall_claim
                    raw = SimpleNamespace(**{**claim, 'text': '' if claim['type'] == 'fact' else claim['text']})
                    validate_recall_claim(raw, facts_by_id, evidence_by_id)
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise ReportRenderError('invalid_report_recall_analysis') from None
        _text(analysis.get('uncertainty', ''))
        if recall and analysis.get('uncertainty') != '':
            raise ReportRenderError('invalid_report_recall_analysis')
    _text(body.get('notice', ''))
    if len(_json(document).encode('utf-8')) > MAX_OBJECT_BYTES:
        raise ReportRenderError('report_export_too_large')
    return body


def _display(value):
    if value is None:
        return '明确未知（null）'
    if isinstance(value, str):
        return _text(value)
    return _json(value)


def safe_source_url(value):
    """A manual citation link only. This module never requests the returned URL."""
    if (not isinstance(value, str) or not value or len(value) > 4096
            or '\\' in value or any(ord(char) < 33 for char in value)):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        _ = parsed.port
    except (ValueError, UnicodeError):
        return None
    return quote(value, safe=":/?#[]@!$&'*+,;=%~._-")


_LABELS = {
    'id': 'ID', 'fingerprint': '内容指纹', 'mode': '原查询模式', 'data_state': '原记录数据状态',
    'created_at': '创建时间', 'completed_at': '完成时间', 'expires_at': '当次分析上下文截止时间',
    'kind': '证据类别', 'source_class': '来源类型', 'source_id': '来源标识', 'source_url': '原始来源',
    'snapshot_id': '冻结快照', 'variant_id': '精确规格', 'raw_hash': '原文 SHA-256', 'parser_version': '解析器版本',
    'observed_at': '原文观察时间', 'verified_at': '核验时间', 'consent_id': '历史回退授权记录',
    'event_id': '测试事件', 'revision': '事件修订', 'verification_status': '核验状态',
    'change_id': '变化事件', 'change_kind': '变化类别', 'change_observed_at': '采纳变化时间',
    'previous_snapshot_id': '变化前快照', 'previous_source_url': '变化前来源',
    'previous_raw_hash': '变化前原文 SHA-256', 'previous_observed_at': '变化前原文观察时间',
    'changes_hash': '冻结差异指纹', 'source_state': '原记录来源状态',
    'question': '分析问题', 'provider': '供应商', 'model': '模型', 'usage': '已确认调用用量',
    'notice': '说明', 'request_id': '分析调用', 'pack_id': '证据包', 'privacy_class': '原证据包隐私分类',
    'evidence_type': '证据领域', 'campaign_number': '召回编号', 'recall_revision_id': '正式召回修订 ID',
    'recall_revision': '正式召回修订序号', 'revision_snapshot_id': '修订首次采纳快照',
    'revision_observed_at': '修订首次观察时间（非公告发布时间）',
    'verification_id': '冻结核验记录', 'verification_query_id': '冻结核验查询',
    'records_hash': '完整产品记录指纹', 'record_count': '本次观察产品记录数',
    'record_scopes': '独立产品记录作用域', 'observation_kind': '观察类别',
    'applicability': '实物适用性（not_assessed 表示未评估）',
    'parser_identity': '解析器部署身份', 'region': '来源地区',
}


def _metadata(values, excluded=()):
    blocks = []
    for key in sorted(values):
        if key in excluded:
            continue
        value = values[key]
        label = _LABELS.get(key, key)
        if key.endswith('url') and isinstance(value, str) and safe_source_url(value):
            blocks.append(Block('link', f'{label}：{value}', links=((value, safe_source_url(value)),)))
        else:
            blocks.append(Block('meta', f'{label}：{_display(value)}'))
    return blocks


def _field_blocks(body):
    """Render the stored decision and all candidates; never import a live policy."""
    blocks = [Block('heading', '保存时字段默认值与权威依据')]
    if 'field_resolutions' not in body:
        return blocks + [Block('paragraph', '此历史报告未记录字段权威判定，保留原事实与冲突；未补算当前结果。')]
    blocks += _metadata(body['field_policy'])
    if not body['field_resolutions']:
        return blocks + [Block('paragraph', '本次所选证据没有轮胎字段权威判定。')]
    states = {'uncontested': '所选证据未形成已知取值矛盾', 'conflict_preferred': '冲突仍存在，具有默认展示偏好',
              'conflict_tied': '并列冲突，无法确定默认值', 'unknown': '仅有缺失或明确未知', 'unavailable': '没有合格默认候选'}
    for resolution in body['field_resolutions']:
        blocks += [Block('subheading', '精确版本 ' + resolution['variant_id']),
                   Block('meta', '冻结范围：' + resolution['scope']), Block('paragraph', resolution['notice'])]
        for field in resolution['fields']:
            blocks += [Block('subheading', field['label'] + ' · ' + field['field']),
                Block('paragraph', '默认展示：' + (_display(field['default_value']) if field['has_default'] else '无法确定')),
                Block('paragraph', '判定：' + states[field['state']]),
                Block('paragraph', '\n'.join(field['reasons']))]
            selected = set(field['default_candidate_ids'])
            for candidate in field['candidates']:
                value = _display(candidate['value']) if candidate['present'] else '未声明此字段'
                blocks += [Block('paragraph', f'候选 {candidate["id"]} · {candidate["source_name"]}：{value}'
                    + (' · 支持默认展示' if candidate['id'] in selected else '')),
                    Block('literal', _json({key: candidate.get(key) for key in (
                        'source_field', 'source_id', 'source_class', 'variant_id', 'snapshot_id', 'fact_version_id',
                        'observed_at', 'published_at', 'verified_at', 'evidence_locator', 'eligible', 'exclusion_reasons', 'dimensions')})),
                    Block('citations', '来源引用', links=((candidate['evidence_id'], '#evidence-' + candidate['evidence_id']),))]
                if candidate.get('fact_ids'):
                    blocks.append(Block('citations', '字段引用', links=tuple((key, '#fact-' + key) for key in candidate['fact_ids'])))
    return blocks


def _blocks(document, body):
    privacy = {'public': '公开来源研究内容', 'private': '私有工作区研究内容', 'restricted': '受限研究内容'}[body['privacy_class']]
    blocks = [Block('title', document['title']), Block('meta', f'报告 {document["report_id"]} · 修订 {document["revision"]}'),
        Block('meta', f'冻结报告创建时间：{document["created_at"]}'),
        Block('paragraph', 'LOCAL SNAPSHOT · 本报告是已选证据的冻结历史记录，不表示导出时的在线参数、在售状态或安全适配认证。'),
        Block('meta', '隐私范围：' + privacy), Block('meta', '导出契约：' + RENDERER_VERSION)]
    if document.get('notes'):
        blocks += [Block('heading', '研究说明'), Block('paragraph', document['notes'])]
    blocks += [Block('heading', '冻结证据范围')]
    blocks += _metadata(body['source_pack'])
    if body.get('notice'):
        blocks.append(Block('paragraph', body['notice']))
    if body.get('recall_boundary'):
        blocks += [Block('heading', '召回公告范围与实物适用性'),
                   Block('paragraph', body['recall_boundary']['notice']),
                   Block('meta', '适用性：not_assessed · 仅公告事实选择 · ' + body['recall_boundary']['policy'])]
    blocks += [Block('heading', '结构化事实与引用', group='fact-' + body['facts'][0]['id'])]
    for fact in body['facts']:
        group = 'fact-' + fact['id']
        blocks += [Block('subheading', f'{fact["id"]} · {fact["field"]}', anchor=group, group=group),
            Block('paragraph', fact['text'], group=group), Block('literal', '结构化值：\n' + _json(fact['value']), group=group),
            Block('citations', '来源引用', links=((fact['evidence_id'], '#evidence-' + fact['evidence_id']),), group=group)]
    blocks.append(Block('heading', '来源冲突与边界'))
    if body['conflicts']:
        for index, conflict in enumerate(body['conflicts'], start=1):
            blocks += [Block('subheading', f'冲突记录 {index}'), Block('literal', _json(conflict))]
    else:
        blocks.append(Block('paragraph', '本报告所选内容未记录冲突；这不表示所有来源已达成一致。'))
    blocks += _field_blocks(body)
    blocks.append(Block('heading', 'AI 分析'))
    analysis = body.get('analysis')
    if analysis is None:
        blocks.append(Block('paragraph', '本报告未附带 AI 分析。保存和导出报告不会自动调用模型。'))
    else:
        blocks += _metadata(analysis, excluded={'claims', 'uncertainty'})
        blocks.append(Block('paragraph', '以下事实文字来自已引用字段；模型推断单独标识，仍需人工核对。引用存在不等于推断正确。'))
        for index, claim in enumerate(analysis['claims'], start=1):
            blocks += [Block('subheading', f'{index}. ' + ('引用事实' if claim['type'] == 'fact' else '模型推断 · 需核对')),
                Block('paragraph', claim['text']),
                Block('citations', '字段引用', links=tuple((key, '#fact-' + key) for key in claim['fact_ids'])),
                Block('citations', '来源引用', links=tuple((key, '#evidence-' + key) for key in claim['evidence_ids']))]
        if body.get('recall_boundary'):
            blocks += [Block('subheading', '适用性未评估'), Block('paragraph', body['recall_boundary']['notice'])]
        else:
            blocks += [Block('subheading', '不确定性'), Block('paragraph', analysis.get('uncertainty') or '未提供额外不确定性说明；不代表没有不确定性。')]
    blocks.append(Block('heading', '证据目录'))
    for evidence in body['evidence']:
        blocks.append(Block('subheading', evidence['id'] + ' · ' + evidence['label'], anchor='evidence-' + evidence['id']))
        blocks += _metadata(evidence, excluded={'id', 'label'})
    blocks.append(Block('footer', '证据数值与来源引用保留其原始范围；人工记录不视为厂商声明，不生成跨测试事件的绝对成绩总榜。'))
    # The same complete text is validated before selecting an output format.
    for block in blocks:
        _text(block.text)
    return blocks


def _md_text(value):
    return _MD_SPECIAL.sub(r'\\\1', html.escape(value, quote=False))


def _markdown(blocks):
    parts = []
    for block in blocks:
        if block.anchor:
            parts.append(f'<a id="{block.anchor}"></a>')
        if block.kind in {'title', 'heading', 'subheading'}:
            parts.append({'title': '# ', 'heading': '## ', 'subheading': '### '}[block.kind] + _md_text(block.text))
        elif block.kind == 'literal':
            parts.append('\n'.join('    ' + line for line in block.text.split('\n')))
        elif block.kind == 'citations':
            parts.append(_md_text(block.text) + '：' + ' · '.join(f'[{_md_text(label)}]({target})' for label, target in block.links))
        elif block.kind == 'link':
            label, target = block.links[0]
            parts.append(_md_text(block.text.split('：', 1)[0]) + f'：[{_md_text(label)}]({target})')
        else:
            parts.append(_md_text(block.text).replace('\n', '  \n'))
    return ('\n\n'.join(parts) + '\n').encode('utf-8')


def _html(document, blocks):
    style_hash = base64.b64encode(hashlib.sha256(_STYLE.encode()).digest()).decode()
    policy = f"default-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'; script-src 'none'; style-src 'sha256-{style_hash}'"
    parts = ['<!doctype html>', '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="' + html.escape(policy, quote=True) + '">',
        '<title>' + html.escape(document['title']) + '</title><style>' + _STYLE + '</style></head><body><main>']
    for block in blocks:
        anchor = f' id="{block.anchor}"' if block.anchor else ''
        if block.kind in {'title', 'heading', 'subheading'}:
            tag = {'title': 'h1', 'heading': 'h2', 'subheading': 'h3'}[block.kind]
            parts.append(f'<{tag}{anchor}>' + html.escape(block.text) + f'</{tag}>')
        elif block.kind == 'literal':
            parts.append('<pre>' + html.escape(block.text) + '</pre>')
        elif block.kind in {'citations', 'link'}:
            label = block.text if block.kind == 'citations' else block.text.split('：', 1)[0]
            links = ' · '.join('<a href="' + html.escape(target, quote=True) + '" rel="noreferrer noopener">' + html.escape(text) + '</a>'
                               for text, target in block.links)
            parts.append('<p class="links">' + html.escape(label) + '：' + links + '</p>')
        else:
            tag = 'footer' if block.kind == 'footer' else 'p'
            cls = ' class="meta"' if block.kind == 'meta' else ''
            parts.append(f'<{tag}{cls}>' + html.escape(block.text) + f'</{tag}>')
    parts.append('</main></body></html>')
    return ('\n'.join(parts) + '\n').encode('utf-8')


class _BoundedOutput(BytesIO):
    def write(self, value):
        if self.tell() + len(value) > MAX_OBJECT_BYTES:
            raise ReportRenderError('report_export_too_large')
        return super().write(value)


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        if hashlib.sha256(_FONT_FILE.read_bytes()).hexdigest() != _FONT_SHA256:
            raise ReportRenderError('report_font_integrity_failed')
        if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_FILE)))
        return pdfmetrics.getFont(_FONT_NAME)
    except ReportRenderError:
        raise
    except Exception:
        raise ReportRenderError('report_font_unavailable') from None


def _wrap(text, font, size, width):
    """Greedy glyph-width wrapping, including continuous CJK and long IDs/URLs."""
    for paragraph in text.expandtabs(4).split('\n'):
        if not paragraph:
            yield ''
            continue
        line, measured = [], 0.0
        for char in paragraph:
            advance = font.face.charWidths[ord(char)] * size / 1000
            if line and measured + advance > width:
                yield ''.join(line)
                line, measured = [], 0.0
            line.append(char)
            measured += advance
        if line:
            yield ''.join(line)


def _pdf(document, blocks):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas
    # ReportLab's dynamic TrueType subsetting shares font state. Serialize the
    # complete render so concurrent exports cannot mix glyph subsets.
    with _FONT_LOCK:
        font = _font()
        all_text = ''.join(block.text + ''.join(label for label, _ in block.links) for block in blocks) + '第 0123456789 页'
        if any(ord(char) not in font.face.charToGlyph or not font.face.charToGlyph[ord(char)]
               for char in all_text if char not in '\n\r\t'):
            raise ReportRenderError('report_pdf_glyph_unavailable')
        output = _BoundedOutput()
        canvas = Canvas(output, pagesize=A4, invariant=1, pageCompression=1, pdfVersion=(1, 4))
        canvas.setTitle(document['title'])
        canvas.setAuthor('Tire Intelligence')
        canvas.setCreator(RENDERER_VERSION)
        page_width, page_height = A4
        left, right, top, bottom = 43.0, 43.0, 48.0, 46.0
        width, y, page = page_width - left - right, page_height - top, 1

        def footer():
            canvas.setFillColor(HexColor('#48606b'))
            canvas.setFont(_FONT_NAME, 8)
            canvas.drawString(left, 25, f'第 {page} 页 · LOCAL SNAPSHOT')

        def next_page():
            nonlocal y, page
            footer()
            canvas.showPage()
            page += 1
            if page > 1000:
                raise ReportRenderError('report_export_too_large')
            y = page_height - top

        def layout(block):
            size = {'title': 20, 'heading': 14, 'subheading': 11, 'meta': 8.5, 'literal': 8.5, 'footer': 8.5}.get(block.kind, 10)
            leading = size * 1.55
            before = 13 if block.kind == 'heading' else 7 if block.kind in {'title', 'subheading'} else 2
            after = 7 if block.kind in {'title', 'heading', 'subheading'} else 5
            text = block.text
            if block.kind == 'citations':
                text += '：' + ' · '.join(label for label, _ in block.links)
            lines = list(_wrap(text, font, size, width))
            return size, leading, before, after, lines

        for index, block in enumerate(blocks):
            size, leading, before, after, lines = layout(block)
            if block.group and (index == 0 or blocks[index - 1].group != block.group):
                group_height = 0.0
                for grouped_index in range(index, len(blocks)):
                    grouped = blocks[grouped_index]
                    if grouped.group != block.group:
                        break
                    _, group_leading, group_before, group_after, group_lines = layout(grouped)
                    group_height += group_before + len(group_lines) * group_leading + group_after
                # Keep a short fact, structured value and citation on one page.
                # Oversized facts still split normally, preserving every line.
                if group_height <= page_height - top - bottom and y - group_height < bottom:
                    next_page()
            # Keep a heading with at least one following body line when possible.
            required = before + leading + (22 if block.kind in {'title', 'heading', 'subheading'} else 0)
            if y - required < bottom:
                next_page()
            y -= before
            if block.anchor:
                canvas.bookmarkHorizontalAbsolute(block.anchor, y + size)
            for line in lines:
                if y - leading < bottom:
                    next_page()
                canvas.setFont(_FONT_NAME, size)
                canvas.setFillColor(HexColor('#48606b') if block.kind in {'meta', 'footer'} else HexColor('#172b35'))
                canvas.drawString(left, y, line)
                if block.kind == 'link':
                    canvas.linkURL(block.links[0][1], (left, y - 2, left + width, y + size), relative=0, thickness=0)
                if block.kind == 'citations':
                    # The text remains readable with PDF viewers that omit links.
                    offset = font.stringWidth(block.text + '：', size)
                    for label, target in block.links:
                        link_width = font.stringWidth(label, size)
                        if offset + link_width <= width:
                            canvas.linkRect('', target[1:], (left + offset, y - 2, left + offset + link_width, y + size), relative=0, thickness=0)
                        offset += font.stringWidth(label + ' · ', size)
                y -= leading
            y -= after
        footer()
        canvas.save()
        return output.getvalue()


def render_report(document: dict, format: str) -> bytes:
    if format not in FORMATS:
        raise ReportRenderError('unsupported_report_format')
    try:
        body = _validate(document)
        blocks = _blocks(document, body)
        data = _markdown(blocks) if format == 'markdown' else _html(document, blocks) if format == 'html' else _pdf(document, blocks)
        if not data or len(data) > MAX_OBJECT_BYTES:
            raise ReportRenderError('report_export_too_large')
        return data
    except ReportRenderError:
        raise
    except Exception:
        raise ReportRenderError('report_render_failed') from None
