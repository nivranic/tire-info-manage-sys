"""Hand-calculated ranking metrics and normal-route evidence reference bindings."""
from copy import deepcopy
import importlib.util
import json
from math import log2
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from tire_api.main import create_app
from tire_api.retrieval_evaluation import EvaluationActuals, EvaluationCorpus, evaluate
from test_knowledge import Sources, seed
from test_core import VARIANT

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('retrieval_evaluation_cli_under_test', ROOT / 'scripts/evaluate_knowledge_retrieval.py')
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def reference(identity):
    return {'kind': 'tire', 'reference': {'kind': 'tire', 'snapshot_id': identity, 'variant_id': 'sku'}}


def inputs():
    first, second, irrelevant = reference('a'), reference('b'), reference('z')
    query = {'mode': 'history', 'text': 'quiet', 'limit': 5}
    corpus = {'schema_version': 'retrieval-evaluation-corpus@1', 'label_provenance': 'independent synthetic labels',
        'cutoffs': [1, 3, 5], 'cases': [{'case_id': 'ranked', 'query': query, 'material': 'synthetic',
            'judgments': [{**first, 'relevance': 3}, {**second, 'relevance': 1}],
            'ordering': [{'before': first, 'after': second}]}]}
    actuals = {'schema_version': 'retrieval-evaluation-actuals@1', 'records': [{'case_id': 'ranked', 'query': query,
        'retrieval_mode': 'lexical', 'result': {'mode': 'history', 'data_state': 'local_snapshot',
            'offset': 0, 'limit': 5, 'items': [irrelevant, second, first]}}]}
    return corpus, actuals


def run(corpus, actuals):
    return evaluate(EvaluationCorpus.model_validate(corpus), EvaluationActuals.model_validate(actuals))


def test_metrics_use_fixed_cutoff_and_graded_ideal_order():
    report = run(*inputs())
    values = report['macro_metrics']['3']
    assert values['precision'] == pytest.approx(2 / 3)
    assert values['recall'] == 1
    assert values['mrr'] == 0.5
    assert values['ndcg'] == pytest.approx((1 / log2(3) + 7 / log2(4)) / (7 + 1 / log2(3)))
    assert report['macro_metrics']['5']['precision'] == 0.4
    assert report['cases'][0]['unjudged_returned'] == 1
    assert report['constraints_passed'] is False


@pytest.mark.parametrize('returned,correct', [([], True), ([reference('a')], False)])
def test_negative_cases_do_not_inflate_positive_metrics(returned, correct):
    corpus, actuals = inputs()
    case = corpus['cases'][0]
    case.update(judgments=[], ordering=[], expect_empty=True)
    actuals['records'][0]['result']['items'] = returned
    report = run(corpus, actuals)
    assert report['macro_metrics'] == {}
    assert report['negative_accuracy'] == int(correct)
    assert report['constraints_passed'] is correct


@pytest.mark.parametrize('mutation', ['duplicate_result', 'missing_case', 'duplicate_case', 'wrong_query', 'wrong_offset', 'wrong_limit', 'wrong_mode', 'invalid_reference'])
def test_invalid_or_mismatched_actuals_are_rejected(mutation):
    corpus, actuals = inputs()
    actual = actuals['records'][0]
    if mutation == 'duplicate_result':
        actual['result']['items'].append(deepcopy(actual['result']['items'][0]))
    elif mutation == 'missing_case':
        actual['case_id'] = 'other'
    elif mutation == 'duplicate_case':
        actuals['records'].append(deepcopy(actual))
    elif mutation == 'wrong_query':
        actual['query'] = {**actual['query'], 'text': 'different'}
    elif mutation == 'wrong_offset':
        actual['result']['offset'] = 1
    elif mutation == 'wrong_limit':
        actual['result']['limit'] = 3
    elif mutation == 'wrong_mode':
        actual['retrieval_mode'] = 'hybrid'
    else:
        actual['result']['items'][0].pop('reference')
    with pytest.raises(ValueError):
        run(corpus, actuals)


@pytest.mark.parametrize('mutation', ['bool_grade', 'duplicate_judgment', 'empty_positive', 'cutoff_over_limit', 'self_order', 'duplicate_cutoff', 'nonzero_query_offset'])
def test_invalid_labels_are_rejected(mutation):
    corpus, actuals = inputs()
    case = corpus['cases'][0]
    if mutation == 'bool_grade':
        case['judgments'][0]['relevance'] = True
    elif mutation == 'duplicate_judgment':
        case['judgments'].append(deepcopy(case['judgments'][0]))
    elif mutation == 'empty_positive':
        case['judgments'] = []
    elif mutation == 'cutoff_over_limit':
        corpus['cutoffs'] = [6]
    elif mutation == 'self_order':
        case['ordering'][0]['after'] = deepcopy(case['ordering'][0]['before'])
    elif mutation == 'duplicate_cutoff':
        corpus['cutoffs'] = [1, 1]
    else:
        case['query']['offset'] = 1
    with pytest.raises(ValidationError):
        run(corpus, actuals)


def test_original_text_collection_keeps_chunk_reference_versions():
    corpus, actuals = inputs()
    html = {'kind': 'source_text', 'reference': {'snapshot_id': 'original', 'chunk_id': 'chunk', 'start': 0, 'end': 20}}
    corpus['cases'][0].update(retrieval_mode='hybrid', collection='original_text',
        judgments=[{**deepcopy(html), 'relevance': 3}], ordering=[])
    actual = actuals['records'][0]
    actual['retrieval_mode'] = 'hybrid'
    actual['result']['original_text'] = {'offset': 0, 'limit': 5, 'items': [html]}
    report = run(corpus, actuals)
    assert report['macro_metrics']['1']['ndcg'] == 1
    actual['result']['original_text'].pop('offset')
    actual['result']['original_text'].pop('limit')
    assert run(corpus, actuals)['macro_metrics']['1']['ndcg'] == 1
    actual['result']['original_text']['items'][0]['reference']['chunk_id'] = 'changed'
    assert run(corpus, actuals)['macro_metrics']['1']['recall'] == 0


def test_normal_knowledge_route_is_evaluated_against_seeded_references():
    app = create_app('sqlite://', Sources())
    try:
        query = {'mode': 'history', 'text': 'qualityprobe', 'filters': {'kind': 'tire'}, 'limit': 5}
        with TestClient(app) as client:
            snapshot, _ = seed(app.state.database, [{**VARIANT, 'id': 'evaluation-sku', 'facts': {'description': 'qualityprobe'}}])
            corpus, _ = inputs()
            expected = {'kind': 'tire', 'reference': {'kind': 'tire', 'snapshot_id': snapshot, 'variant_id': 'evaluation-sku'}}
            corpus['cases'][0].update(query=query, judgments=[{**expected, 'relevance': 3}], ordering=[])
            response = client.post('/v1/knowledge/search', json=query)
            assert response.status_code == 200
            actuals = {'schema_version': 'retrieval-evaluation-actuals@1', 'records': [
                {'case_id': 'ranked', 'query': query, 'retrieval_mode': 'lexical', 'result': response.json()}]}
            report = run(corpus, actuals)
        assert report['constraints_passed'] and report['macro_metrics']['1']['recall'] == 1
    finally:
        app.state.database.close()
        app.state.telemetry.shutdown()


def test_cli_binds_inputs_and_keeps_existing_output(tmp_path, monkeypatch):
    corpus, actuals = inputs()
    corpus_path, actuals_path, output = [tmp_path / name for name in ('corpus.json', 'actuals.json', 'report.json')]
    corpus_path.write_text(json.dumps(corpus), encoding='utf-8')
    actuals_path.write_text(json.dumps(actuals), encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['evaluate', '--corpus', str(corpus_path), '--actuals', str(actuals_path), '--output', str(output)])
    assert CLI.main() == 2
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['case_count'] == 1 and report['constraints_passed'] is False
    assert report['input_bindings']['corpus']['byte_count'] == corpus_path.stat().st_size
    before = output.read_bytes()
    assert CLI.main() == 1
    assert output.read_bytes() == before


@pytest.mark.parametrize('raw', [b'{"value":1,"value":2}', b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e999}', b'\xff', b'[]', b'x' * 512001],
                         ids=['duplicate-key', 'nan', 'infinity', 'overflow', 'invalid-utf8', 'array', 'oversized'])
def test_cli_rejects_invalid_json_without_echoing_input(tmp_path, monkeypatch, capsys, raw):
    corpus, actuals, output = [tmp_path / name for name in ('corpus.json', 'actuals.json', 'report.json')]
    corpus.write_bytes(raw)
    actuals.write_bytes(b'{}')
    monkeypatch.setattr('sys.argv', ['evaluate', '--corpus', str(corpus), '--actuals', str(actuals), '--output', str(output)])
    assert CLI.main() == 1
    assert not output.exists()
    assert json.loads(capsys.readouterr().out) == {'error_code': 'retrieval_evaluation_input_invalid'}
