"""Offline export equivalence, safe serialization, embedded CJK and pagination."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import socket
from unittest.mock import patch

from pypdf import PdfReader
import pypdfium2 as pdfium
import pytest

from tire_api import report_rendering as rendering
from tire_api.report_rendering import RENDERER_VERSION, ReportRenderError, render_report, safe_source_url


def sample_document():
    fact = {'id': 'f1', 'evidence_id': 'e1', 'field': 'UTQG 磨耗指数', 'value': 420,
            'text': '示例精确轮胎：UTQG 磨耗指数 = 420'}
    delta = {'before': None, 'after': None, 'before_present': False, 'after_present': True}
    return {'schema_version': 'research-report@1', 'report_id': 'report-synthetic-001',
        'title': '合成轮胎研究报告 · 中文证据', 'notes': '仅用于导出测试。研究说明与原始事实分开。',
        'revision': 1, 'created_at': '2026-09-27T12:00:00+00:00',
        'body': {'data_state': 'local_snapshot', 'privacy_class': 'private',
            'source_pack': {'id': 'pack-synthetic-001', 'fingerprint': 'a' * 64, 'mode': 'history',
                'data_state': 'local_snapshot', 'privacy_class': 'public', 'created_at': '2026-09-27T11:00:00+00:00',
                'expires_at': '2026-09-27T11:30:00+00:00'},
            'evidence': [
                {'id': 'e1', 'kind': 'manufacturer_official', 'label': '示例厂商 · 精确 SKU-001',
                 'source_id': 'synthetic-official', 'variant_id': 'variant-exact-001',
                 'snapshot_id': 'snapshot-after-001', 'source_url': 'https://example.com/tires/sku-001',
                 'observed_at': '2026-09-26T09:00:00+00:00', 'verified_at': '2026-09-27T10:00:00+00:00',
                 'raw_hash': 'b' * 64, 'parser_version': 'synthetic@1'},
                {'id': 'e2', 'kind': 'change_event', 'label': '示例规格历史变化', 'change_id': 'change-001',
                 'source_id': 'synthetic-official', 'variant_id': 'variant-exact-001',
                 'snapshot_id': 'snapshot-after-001', 'previous_snapshot_id': 'snapshot-before-001',
                 'source_url': 'https://example.com/tires/sku-001',
                 'previous_source_url': 'https://example.com/tires/sku-001-before',
                 'observed_at': '2026-09-26T09:00:00+00:00', 'previous_observed_at': '2026-09-25T09:00:00+00:00',
                 'change_observed_at': '2026-09-27T10:00:00+00:00', 'change_kind': 'facts_changed',
                 'previous_raw_hash': 'c' * 64, 'raw_hash': 'b' * 64, 'changes_hash': 'd' * 64,
                 'data_state': 'local_snapshot'}],
            'facts': [fact, {'id': 'f2', 'evidence_id': 'e2', 'field': '湿地字段 · 冻结差异',
                'value': delta, 'text': '示例规格：未声明此字段 → 明确未知（null）'}],
            'conflicts': [{'scope': 'unselected_formal_evidence', 'resolution': 'not_evaluated',
                          'notice': '另有未选入的正式证据；不得认定来源一致。'}],
            'analysis': {'id': 'analysis-001', 'question': '解释所选历史证据', 'provider': 'synthetic-not-live',
                'model': 'fixture-model', 'created_at': '2026-09-27T11:01:00+00:00',
                'completed_at': '2026-09-27T11:02:00+00:00',
                'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120},
                'claims': [
                    {'type': 'fact', 'text': fact['text'], 'fact_ids': ['f1'], 'evidence_ids': ['e1']},
                    {'type': 'inference', 'text': '这次记录不足以推断湿地性能提升。', 'fact_ids': ['f2'], 'evidence_ids': ['e2']}],
                'uncertainty': '缺少同条件的性能测试。'},
            'notice': '冻结研究集合；原始证据优先于 AI 摘要。'}}


class ParsedHTML(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.ids, self.links, self.meta = [], [], [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs.get('href'))
        if tag == 'meta':
            self.meta.append(attrs)

    def handle_data(self, data):
        self.text.append(data)


def pdf_text(data):
    return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_all_formats_preserve_the_same_frozen_evidence_and_inference(format):
    document = sample_document()
    before = deepcopy(document)
    data = render_report(document, format)
    assert document == before and 0 < len(data) <= rendering.MAX_OBJECT_BYTES
    content = pdf_text(data) if format == 'pdf' else ''.join(ParsedHTML(data.decode()).text) if format == 'html' else data.decode().replace('\\', '')
    for marker in ('合成轮胎研究报告', 'LOCAL SNAPSHOT', '私有工作区', 'snapshot-before-001',
                   '2026-09-25T09:00:00+00:00', '2026-09-27T10:00:00+00:00',
                   'before_present', 'after_present', '未声明此字段', '明确未知（null）',
                   '模型推断', '缺少同条件的性能测试', '另有未选入', '原证据包隐私分类：public', 'e1', 'f1', RENDERER_VERSION):
        assert marker in content, (format, marker)


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_exports_are_deterministic_and_metadata_order_independent(format):
    document = sample_document()
    first = render_report(document, format)
    second = deepcopy(document)
    second['body']['source_pack'] = dict(reversed(list(second['body']['source_pack'].items())))
    second['body']['evidence'][0] = dict(reversed(list(second['body']['evidence'][0].items())))
    assert render_report(second, format) == first


def test_html_and_markdown_treat_source_markup_and_links_as_data():
    document = sample_document()
    canary = '<script>window.reportCanary=1</script><img src="file:///secret"><svg onload="attack()">'
    document['notes'] = canary + '\n[x](javascript:alert(1))\n```html\n# injected heading\n```'
    document['body']['evidence'][0]['source_url'] = 'javascript:alert(1)'
    markup = render_report(document, 'html').decode()
    parsed = ParsedHTML(markup)
    assert not {'script', 'img', 'svg', 'iframe', 'object', 'link'} & set(parsed.tags)
    assert canary in ''.join(parsed.text)
    assert all(target.startswith(('https://', 'http://', '#')) for target in parsed.links)
    assert {'fact-f1', 'fact-f2', 'evidence-e1', 'evidence-e2'} <= set(parsed.ids)
    assert any(meta.get('http-equiv') == 'Content-Security-Policy' and "default-src 'none'" in meta['content'] for meta in parsed.meta)
    markdown = render_report(document, 'markdown').decode()
    assert '<script>' not in markdown and '<img ' not in markdown and '<svg ' not in markdown
    assert '[x](javascript:' not in markdown and '\\[x\\]' in markdown
    assert '```html' not in markdown and '\\`\\`\\`html' in markdown


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'data:text/html,test', 'file:///secret',
                                  'https://user:password@example.com', 'https://example.com\\evil',
                                  'https://example.com/\nattack', 'https://example.com:bad/'])
def test_unsafe_urls_never_become_active_citations(value):
    assert safe_source_url(value) is None


def test_safe_url_escapes_markdown_delimiters_without_fetching():
    target = safe_source_url('https://example.com/tire(foo)?q="bar"&x=1')
    assert target == 'https://example.com/tire%28foo%29?q=%22bar%22&x=1'
    with patch.object(socket, 'create_connection', side_effect=AssertionError('No networking during export')):
        for format in ('markdown', 'html', 'pdf'):
            assert render_report(sample_document(), format)


@pytest.mark.parametrize('mutation', ['foreign_evidence', 'foreign_fact', 'wrong_claim_source', 'freeform_fact',
                                    'duplicate_evidence', 'duplicate_fact', 'wrong_state', 'nan', 'bad_unicode'])
def test_invalid_or_unbound_document_fails_closed(mutation):
    document = sample_document()
    body = document['body']
    if mutation == 'foreign_evidence': body['facts'][0]['evidence_id'] = 'foreign'
    elif mutation == 'foreign_fact': body['analysis']['claims'][0]['fact_ids'] = ['foreign']
    elif mutation == 'wrong_claim_source': body['analysis']['claims'][0]['evidence_ids'] = ['e2']
    elif mutation == 'freeform_fact': body['analysis']['claims'][0]['text'] = '凭空生成的厂商事实'
    elif mutation == 'duplicate_evidence': body['evidence'].append(deepcopy(body['evidence'][0]))
    elif mutation == 'duplicate_fact': body['facts'].append(deepcopy(body['facts'][0]))
    elif mutation == 'wrong_state': body['data_state'] = 'live'
    elif mutation == 'nan': body['facts'][0]['value'] = float('nan')
    else: document['notes'] = '\ud800'
    for format in ('markdown', 'html', 'pdf'):
        with pytest.raises(ReportRenderError):
            render_report(document, format)


def test_missing_analysis_is_explicit_and_requires_no_provider():
    document = sample_document()
    document['body']['analysis'] = None
    assert '未附带 AI 分析' in pdf_text(render_report(document, 'pdf'))


def test_pdf_is_portable_embeds_true_type_and_renders_chinese():
    data = render_report(sample_document(), 'pdf')
    reader = PdfReader(BytesIO(data))
    embedded = []
    for page in reader.pages:
        for reference in page['/Resources']['/Font'].values():
            font = reference.get_object()
            descriptor = font.get('/FontDescriptor')
            if descriptor:
                descriptor = descriptor.get_object()
                if '/FontFile2' in descriptor:
                    embedded.append(font)
                    assert len(descriptor['/FontFile2'].get_data()) > 1000
                    assert '/ToUnicode' in font
    assert embedded and all('TireEvidenceSC-Regular' in str(font['/BaseFont']) for font in embedded)
    with pdfium.PdfDocument(data) as pdf:
        assert len(pdf) == len(reader.pages)
        for index in {0, len(pdf) - 1}:
            page = pdf[index]
            bitmap = page.render(scale=1)
            image = bitmap.to_pil()
            assert image.width > 500 and image.height > 700
            extrema = image.convert('L').getextrema()
            assert extrema[0] < 100 and extrema[1] == 255
            image.close()
            bitmap.close()
            page.close()


def test_long_paragraph_and_unbroken_token_paginate_without_truncation():
    document = sample_document()
    token = 'VeryLongFrozenIdentifier0123456789' * 120
    document['notes'] = '中文长段落验证。' * 500 + '\n' + token + '\n尾部必须完整保留'
    data = render_report(document, 'pdf')
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) > 4
    extracted = '\n'.join(page.extract_text() for page in reader.pages)
    assert '尾部必须完整保留' in extracted and '变化前快照' in extracted
    # Remove generated footer text and pagination whitespace, preserving all
    # characters of the long source token across its line/page boundaries.
    import re
    body = re.sub(r'第 \d+ 页 · LOCAL SNAPSHOT', '', extracted)
    assert token in ''.join(body.split())


def test_pdf_concurrent_rendering_does_not_mix_font_subsets():
    documents = [sample_document() for _ in range(4)]
    for index, document in enumerate(documents):
        document['notes'] = f'并发中文证据样本 {index} · ' + ['轮胎', '湿地', '噪声', '舒适'][index]
    expected = [render_report(document, 'pdf') for document in documents]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda document: render_report(document, 'pdf'), documents))
    assert actual == expected


def test_pdf_short_facts_keep_their_value_and_citation_on_the_same_page():
    document = sample_document()
    document['body']['analysis'] = None
    document['body']['facts'] = [
        {'id': f'f{index}', 'evidence_id': 'e1', 'field': f'分页字段-{index:02}',
         'text': f'完整原文-{index:02}', 'value': f'完整数值-{index:02}'} for index in range(1, 25)]
    pages = [page.extract_text() for page in PdfReader(BytesIO(render_report(document, 'pdf'))).pages]
    assert len(pages) > 3
    for index in range(1, 25):
        page = next(text for text in pages if f'分页字段-{index:02}' in text)
        assert f'完整原文-{index:02}' in page and f'完整数值-{index:02}' in page
        assert page.index(f'完整数值-{index:02}') < page.rindex('来源引用：e1')
        if index == 1:
            assert '结构化事实与引用' in page


def test_pdf_oversized_fact_still_spans_pages_without_losing_its_citation():
    document = sample_document()
    document['body']['analysis'] = None
    document['body']['facts'] = [{'id': 'f1', 'evidence_id': 'e1', 'field': '跨页长字段',
        'text': '完整来源原文' * 1000 + '长事实尾标记', 'value': '最终结构化值'}]
    pages = [page.extract_text() for page in PdfReader(BytesIO(render_report(document, 'pdf'))).pages]
    assert len(pages) > 4
    tail = next(text for text in pages if '长事实尾标记' in text)
    assert '最终结构化值' in tail and '来源引用：e1' in tail


def test_pdf_uncovered_character_and_font_integrity_fail_explicitly(monkeypatch, tmp_path):
    document = sample_document()
    document['notes'] = chr(0x10FFFF)
    with pytest.raises(ReportRenderError, match='report_pdf_glyph_unavailable'):
        render_report(document, 'pdf')
    corrupt = tmp_path / 'font.ttf'
    corrupt.write_bytes(b'invalid font')
    monkeypatch.setattr(rendering, '_FONT_FILE', corrupt)
    with pytest.raises(ReportRenderError, match='report_font_integrity_failed'):
        render_report(sample_document(), 'pdf')
    monkeypatch.setattr(rendering, '_FONT_FILE', tmp_path / 'missing.ttf')
    with pytest.raises(ReportRenderError, match='report_font_unavailable'):
        render_report(sample_document(), 'pdf')


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_output_bounds_fail_instead_of_truncating(monkeypatch, format):
    monkeypatch.setattr(rendering, 'MAX_OBJECT_BYTES', 100)
    with pytest.raises(ReportRenderError, match='report_export_too_large'):
        render_report(sample_document(), format)


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_serialized_output_is_bounded_even_when_input_fits(monkeypatch, format):
    document = sample_document()
    document['notes'] = '[]()*_<>\\' * 400
    input_size = len(rendering._json(document).encode('utf-8'))
    data = render_report(document, format)
    assert len(data) > input_size
    monkeypatch.setattr(rendering, 'MAX_OBJECT_BYTES', len(data) - 1)
    with pytest.raises(ReportRenderError, match='report_export_too_large'):
        render_report(document, format)


def test_actual_report_backend_document_contract_uses_all_three_formats():
    from types import SimpleNamespace
    from tire_api.db import utcnow
    from tire_api.reports import document_for
    sample = sample_document()
    report = SimpleNamespace(id=sample['report_id'], created_at=utcnow(), body=sample['body'])
    revision = SimpleNamespace(title=sample['title'], notes=sample['notes'], revision=3)
    document = document_for(report, revision)
    for format in ('markdown', 'html', 'pdf'):
        assert render_report(document, format)


def test_font_provenance_and_license_match_the_packaged_derivative():
    root = Path(rendering.__file__).parent / 'assets' / 'fonts'
    provenance = json.loads((root / 'provenance.json').read_text(encoding='utf-8'))
    assert provenance['commit'] == 'a85815a42757630ce188fdad368c2dfc444d4773'
    assert provenance['output_sha256'] == rendering._FONT_SHA256
    for name, key in [('TireEvidenceSC-Regular.ttf', 'output_sha256'), ('OFL.txt', 'license_sha256')]:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == provenance[key]
    assert 'SIL OPEN FONT LICENSE Version 1.1' in (root / 'OFL.txt').read_text(encoding='utf-8')
