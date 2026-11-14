"""Synthetic PDF pages through the fixed extractor and actual bounded children."""
import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import os
import shutil

import pytest

from tire_api import document_pdf, parser_bundles as bundles, parser_runtime as runtime


def pdf_bytes(pages=('Original tyre text', 'Second page'), *, encrypted=False):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    output = BytesIO()
    canvas = Canvas(output, invariant=1, pageCompression=0)
    for text in pages:
        canvas.setFont('STSong-Light', 12)
        if text:
            canvas.drawString(24, 740, text)
        canvas.showPage()
    canvas.save()
    if encrypted:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter(clone_from=PdfReader(BytesIO(output.getvalue())))
        writer.encrypt('synthetic-test-only')
        output = BytesIO()
        writer.write(output)
    return output.getvalue()


def test_page_text_unicode_hashes_and_determinism():
    body = pdf_bytes(('轮胎正文  第一页', 'Second page 🛞'))
    result = document_pdf.parse_document_pdf(body, 'document-one')
    assert result == document_pdf.parse_document_pdf(body, 'document-one')
    assert result['status'] == 'text_available' and result['page_count'] == 2
    assert [page['text'] for page in result['pages']] == ['轮胎正文 第一页', 'Second page 🛞']
    assert result['characters'] == sum(len(page['text']) for page in result['pages'])
    assert result['extractor_version'] == document_pdf.extractor_version()
    assert all(page['text_hash'] == hashlib.sha256(page['text'].encode()).hexdigest() for page in result['pages'])


@pytest.mark.parametrize('pages,state', [(('', ''), 'no_extractable_text'), (('Visible', ''), 'partial_text')])
def test_blank_or_scanned_text_requires_review(pages, state):
    result = document_pdf.parse_document_pdf(pdf_bytes(pages), 'document-one')
    assert result['status'] == state
    assert result['pages'][-1]['status'] == 'no_extractable_text'
    assert result['pages'][-1]['text'] == ''


def test_encrypted_pdf_has_explicit_state_without_password_discovery():
    result = document_pdf.parse_document_pdf(pdf_bytes(encrypted=True), 'document-one')
    assert result['status'] == 'encrypted' and result['page_count'] is None
    assert result['pages'] == [] and result['characters'] == 0


@pytest.mark.parametrize('body', [b'not-pdf', b'%PDF-1.7\nsynthetic broken file\n%%EOF'])
def test_invalid_pdf_has_a_fixed_error(body):
    with pytest.raises(document_pdf.DocumentPDFError, match='^document_pdf_invalid$'):
        document_pdf.parse_document_pdf(body, 'document-one')


@pytest.mark.parametrize('name,maximum,code', [
    ('MAX_PAGES', 1, 'document_pdf_too_many_pages'),
    ('MAX_PAGE_CHARACTERS', 3, 'document_pdf_text_too_large'),
    ('MAX_TEXT_CHARACTERS', 8, 'document_pdf_text_too_large'),
])
def test_declared_text_and_page_bounds(monkeypatch, name, maximum, code):
    monkeypatch.setattr(document_pdf, name, maximum)
    with pytest.raises(document_pdf.DocumentPDFError, match='^' + code + '$'):
        document_pdf.parse_document_pdf(pdf_bytes(), 'document-one')


@pytest.fixture
def installation(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for path in runtime._ROOT.rglob('*.py'):
        target = source / path.relative_to(runtime._ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    monkeypatch.setattr(runtime, '_ROOT', source)
    return source


def execute(body):
    descriptor = runtime.current_parser(document_pdf.SOURCE_ID)
    return asyncio.run(runtime.parse_isolated(document_pdf.SOURCE_ID, body, {'document_id': 'document-one'},
        descriptor['parser_version'], descriptor['parser_digest']))


def test_actual_child_preserves_pages_and_reaps_resources(installation):
    body = pdf_bytes(('轮胎正文', 'Second page 🛞', ''))
    result = execute(body)
    assert result['payload'] == document_pdf.parse_document_pdf(body, 'document-one')
    receipt = result['receipt']
    assert receipt['pid'] != os.getpid() and receipt['exit_code'] == 0 and receipt['reaped']
    assert receipt['python_network_guard'] and receipt['network_enforced'] is False
    assert receipt['source_id'] == document_pdf.SOURCE_ID and receipt['stderr_bytes'] == 0


def test_actual_child_transports_only_fixed_pdf_errors(installation):
    with pytest.raises(runtime.ParserRunError, match='^document_pdf_invalid$') as caught:
        execute(b'%PDF-synthetic-invalid')
    assert caught.value.receipt['reaped'] and caught.value.receipt['exit_code'] == 0


@pytest.mark.parametrize('historical', [False, True])
def test_pdf_capability_requires_the_complete_reviewed_catalog(installation, historical):
    if historical:
        from test_parser_bundles import pre_bridgestone_install
        catalog = {key: value for key, value in runtime.source_catalog().items()
                   if key in bundles._DOCUMENT_SOURCES}
        pre_bridgestone_install(installation)
        manifest = bundles.snapshot_manifest(installation, catalog, runtime.PROTOCOL, runtime.limits())
    else:
        manifest = runtime._deployed_manifest()
    expected = bundles._DOCUMENT_SOURCES if historical else bundles._YOKOHAMA_SOURCES
    assert set(manifest['parsers']) == set(expected)
    for missing in ('workspace-pdf-text', 'document_pdf.py'):
        changed = deepcopy(manifest)
        del changed['parsers' if missing == 'workspace-pdf-text' else 'files'][missing]
        changed['bundle_id'] = bundles.digest({key: value for key, value in changed.items() if key != 'bundle_id'})
        if missing == 'workspace-pdf-text' and historical:
            assert bundles.checked_manifest(changed, protocol=runtime.PROTOCOL, limits=runtime.limits()) == changed
            with pytest.raises(runtime.ParserRunError, match='^parser_source_not_allowed$'):
                runtime.descriptor_for_manifest(changed, document_pdf.SOURCE_ID)
        else:
            with pytest.raises(bundles.BundleError, match='^parser_bundle_manifest_invalid$'):
                bundles.checked_manifest(changed, protocol=runtime.PROTOCOL, limits=runtime.limits())
