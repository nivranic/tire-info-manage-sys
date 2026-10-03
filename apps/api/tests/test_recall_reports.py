"""Offline recall report checks; synthetic provenance is not live source acceptance."""
from copy import deepcopy

import pytest

from tire_api.report_rendering import ReportRenderError, render_report
from test_recall_grounding import answer, claim, recall_pack
from test_report_rendering import ParsedHTML, pdf_text, sample_document
from test_recalls import record


def document(*, empty=False):
    result = sample_document()
    result['schema_version'] = 'research-report@3'
    payload = recall_pack([] if empty else [record('SYNTHETIC <script>not executable</script>')], mixed=False)
    result['body'].update({key: payload[key] for key in ('facts', 'evidence', 'conflicts', 'recall_policy', 'recall_boundary')})
    selected = claim(['rcf_0'], ['e1']) if empty else claim(['rcf_0', 'f1'], ['e1'])
    result['body']['analysis'].update({key: value for key, value in answer(payload, [selected]).items()
                                       if key in ('claims', 'uncertainty')})
    return result


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
@pytest.mark.parametrize('empty', [False, True])
def test_recall_exports_preserve_boundary_scope_and_frozen_times(format, empty):
    sample = document(empty=empty)
    original = deepcopy(sample)
    exported = render_report(sample, format)
    text = (pdf_text(exported) if format == 'pdf' else ''.join(ParsedHTML(exported.decode()).text)
            if format == 'html' else exported.decode().replace('\\', ''))
    for marker in ('not_assessed', 'DOT/TIN', '生产批次', '空响应不表示无召回', '首次观察时间不等于公告发布时间',
                   '23T001000', '2026-09-20T12:00:00+00:00', '冻结核验记录', 'frozen-research-export@4'):
        assert marker in text, (format, marker)
    if empty:
        assert '本次空响应观察' in text and len(sample['body']['facts']) == 4
    else:
        assert '<script>not executable</script>' in text
        if format == 'html':
            assert 'script' not in ParsedHTML(exported.decode()).tags
    assert sample == original


@pytest.mark.parametrize('mutation', ['uncertainty', 'inference', 'boundary', 'record_scope', 'value', 'schema'])
def test_offline_export_rejects_forged_recall_body_or_unsafe_analysis(mutation):
    sample = document()
    if mutation == 'uncertainty': sample['body']['analysis']['uncertainty'] = '已确认安全'
    if mutation == 'inference': sample['body']['analysis']['claims'][0].update(type='inference', text='车辆适用')
    if mutation == 'boundary': sample['body']['recall_boundary'] = {'applicability': 'safe'}
    if mutation == 'record_scope': sample['body']['facts'][4]['record_key'] = 'different'
    if mutation == 'value': sample['body']['facts'][4]['value'] = 'fake'
    if mutation == 'schema': sample['schema_version'] = 'research-report@2'
    with pytest.raises(ReportRenderError):
        render_report(sample, 'markdown')


@pytest.mark.parametrize('schema', ['research-report@1', 'research-report@2', 'research-report@3'])
def test_existing_non_recall_report_schemas_keep_their_original_body(schema):
    sample = sample_document()
    sample['schema_version'] = schema
    original = deepcopy(sample)
    assert b'LOCAL SNAPSHOT' in render_report(sample, 'html')
    assert sample == original and 'recall_boundary' not in sample['body']


@pytest.mark.parametrize('format', ['markdown', 'html', 'pdf'])
def test_frozen_recall_export_uses_saved_version_when_active_policy_changes(monkeypatch, format):
    from tire_api import recall_evidence
    from tire_api.ai_recall_contract import validate_recall_payload
    sample = document()
    original = deepcopy(sample)
    expected = render_report(sample, format)
    future_policy = {'version': 'recall-fact-selection@2', 'digest': 'f' * 64}
    future_boundary = {**sample['body']['recall_boundary'], 'policy': 'recall-fact-selection@2', 'notice': 'Future policy'}
    monkeypatch.setattr(recall_evidence, 'recall_policy_descriptor', lambda: deepcopy(future_policy))
    monkeypatch.setattr(recall_evidence, 'recall_boundary_descriptor', lambda: deepcopy(future_boundary))
    assert render_report(sample, format) == expected
    assert sample == original
    # Frozen export compatibility must never authorize a new request with stale policy.
    with pytest.raises(ValueError, match='invalid_recall_contract'):
        validate_recall_payload({**sample['body'], 'purpose': 'recall_research'})


@pytest.mark.parametrize('mutation', ['unknown_version', 'digest', 'boundary'])
def test_frozen_recall_version_dispatch_still_rejects_tampered_saved_contract(mutation):
    sample = document()
    if mutation == 'unknown_version': sample['body']['recall_policy']['version'] = 'recall-fact-selection@999'
    if mutation == 'digest': sample['body']['recall_policy']['digest'] = '0' * 64
    if mutation == 'boundary': sample['body']['recall_boundary']['notice'] = 'invented safety text'
    with pytest.raises(ReportRenderError):
        render_report(sample, 'markdown')
