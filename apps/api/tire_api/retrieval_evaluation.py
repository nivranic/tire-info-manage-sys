"""Offline retrieval metrics over independently labelled, exact evidence references."""
from math import log2
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from .domain import StrictModel, digest
from .knowledge import KnowledgeSearch


class Closed(StrictModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class Reference(Closed):
    kind: Literal['tire', 'vehicle', 'test_event', 'recall', 'source_text', 'document_text']
    reference: dict[str, JsonValue] = Field(min_length=1, max_length=16)

    def key(self):
        return digest({'kind': self.kind, 'reference': self.reference})


class Judgment(Reference):
    relevance: int = Field(ge=0, le=3)


class Ordering(Closed):
    before: Reference
    after: Reference


class EvaluationCase(Closed):
    case_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,79}$')
    query: KnowledgeSearch
    retrieval_mode: Literal['lexical', 'hybrid'] = 'lexical'
    collection: Literal['structured', 'original_text'] = 'structured'
    material: Literal['synthetic', 'real_source', 'mixed']
    judgments: list[Judgment] = Field(default_factory=list, max_length=300)
    expect_empty: bool = False
    ordering: list[Ordering] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def consistent(self):
        keys = [judgment.key() for judgment in self.judgments]
        if len(keys) != len(set(keys)) or self.query.offset != 0:
            raise ValueError('retrieval_evaluation_case_invalid')
        positives = any(judgment.relevance > 0 for judgment in self.judgments)
        if positives == self.expect_empty or self.expect_empty and self.ordering:
            raise ValueError('retrieval_evaluation_labels_invalid')
        pairs = [(pair.before.key(), pair.after.key()) for pair in self.ordering]
        if (len(pairs) != len(set(pairs))
                or any(before == after or before not in keys or after not in keys for before, after in pairs)):
            raise ValueError('retrieval_evaluation_order_invalid')
        if self.collection == 'original_text' and self.retrieval_mode != 'hybrid':
            raise ValueError('retrieval_evaluation_collection_invalid')
        return self


class EvaluationCorpus(Closed):
    schema_version: Literal['retrieval-evaluation-corpus@1']
    label_provenance: str = Field(min_length=5, max_length=1000)
    cutoffs: list[int] = Field(default_factory=lambda: [1, 3, 5], min_length=1, max_length=30)
    cases: list[EvaluationCase] = Field(min_length=1, max_length=300)

    @model_validator(mode='after')
    def unique_cases_and_cutoffs(self):
        ids = [case.case_id for case in self.cases]
        if (len(ids) != len(set(ids)) or self.cutoffs != sorted(set(self.cutoffs))
                or any(type(value) is not int or not 1 <= value <= 30 for value in self.cutoffs)
                or any(case.query.limit < max(self.cutoffs) for case in self.cases)):
            raise ValueError('retrieval_evaluation_corpus_invalid')
        return self


class Actual(Closed):
    case_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,79}$')
    query: KnowledgeSearch
    retrieval_mode: Literal['lexical', 'hybrid']
    result: dict[str, JsonValue]


class EvaluationActuals(Closed):
    schema_version: Literal['retrieval-evaluation-actuals@1']
    records: list[Actual] = Field(min_length=1, max_length=300)


def ranked_references(case, actual):
    if actual.query.model_dump() != case.query.model_dump() or actual.retrieval_mode != case.retrieval_mode:
        raise ValueError('retrieval_evaluation_query_mismatch')
    result = actual.result
    if result.get('mode') != 'history' or result.get('data_state') != 'local_snapshot':
        raise ValueError('retrieval_evaluation_result_invalid')
    collection = result.get('original_text') if case.collection == 'original_text' else result
    if (type(collection) is not dict or type(collection.get('items')) is not list
            or type(collection.get('offset', result.get('offset'))) is not int
            or collection.get('offset', result.get('offset')) != 0
            or type(collection.get('limit', result.get('limit'))) is not int
            or collection.get('limit', result.get('limit')) != case.query.limit
            or len(collection['items']) > case.query.limit):
        raise ValueError('retrieval_evaluation_page_invalid')
    references = []
    for item in collection['items']:
        if type(item) is not dict:
            raise ValueError('retrieval_evaluation_reference_invalid')
        reference = Reference.model_validate({'kind': item.get('kind'), 'reference': item.get('reference')})
        references.append(reference.key())
    if len(references) != len(set(references)):
        raise ValueError('retrieval_evaluation_duplicate_result')
    return references


def metrics_at(cutoff, references, judgments):
    grades = [judgments.get(key, 0) for key in references[:cutoff]]
    positives = sum(grade > 0 for grade in judgments.values())
    hits = sum(grade > 0 for grade in grades)
    ideal = sorted(judgments.values(), reverse=True)[:cutoff]
    dcg = sum((2 ** grade - 1) / log2(rank + 2) for rank, grade in enumerate(grades))
    idcg = sum((2 ** grade - 1) / log2(rank + 2) for rank, grade in enumerate(ideal))
    return {'precision': hits / cutoff, 'recall': hits / positives,
            'mrr': next((1 / rank for rank, grade in enumerate(grades, 1) if grade > 0), 0.0),
            'ndcg': dcg / idcg}


def evaluate(corpus: EvaluationCorpus, actuals: EvaluationActuals):
    records = {record.case_id: record for record in actuals.records}
    if len(records) != len(actuals.records) or set(records) != {case.case_id for case in corpus.cases}:
        raise ValueError('retrieval_evaluation_case_mismatch')
    results = []
    for case in corpus.cases:
        references = ranked_references(case, records[case.case_id])
        judgments = {judgment.key(): judgment.relevance for judgment in case.judgments}
        ranks = {key: rank for rank, key in enumerate(references, 1)}
        ordering = [pair.before.key() in ranks and pair.after.key() in ranks
                    and ranks[pair.before.key()] < ranks[pair.after.key()] for pair in case.ordering]
        empty_correct = not references if case.expect_empty else None
        results.append({'case_id': case.case_id, 'material': case.material,
            'retrieval_mode': case.retrieval_mode, 'collection': case.collection,
            'returned': len(references), 'judged_returned': sum(key in judgments for key in references),
            'unjudged_returned': sum(key not in judgments for key in references),
            'positive_judgments': sum(grade > 0 for grade in judgments.values()),
            'expect_empty': case.expect_empty, 'empty_correct': empty_correct,
            'ordering': ordering, 'constraints_passed': all(ordering) and empty_correct is not False,
            'metrics': {} if case.expect_empty else {
                str(cutoff): metrics_at(cutoff, references, judgments) for cutoff in corpus.cutoffs}})
    positive = [row for row in results if not row['expect_empty']]
    negative = [row for row in results if row['expect_empty']]
    aggregate = {}
    if positive:
        for cutoff in corpus.cutoffs:
            averages = {}
            for metric in ('precision', 'recall', 'mrr', 'ndcg'):
                total = sum(row['metrics'][str(cutoff)][metric] for row in positive)
                averages[metric] = total / len(positive)
            aggregate[str(cutoff)] = averages
    return {'schema_version': 'retrieval-evaluation-report@1', 'state': 'evaluated',
            'corpus_fingerprint': digest(corpus.model_dump(mode='json')),
            'actuals_fingerprint': digest(actuals.model_dump(mode='json')),
            'label_provenance': corpus.label_provenance, 'case_count': len(results),
            'positive_cases': len(positive), 'negative_cases': len(negative),
            'negative_accuracy': sum(row['empty_correct'] for row in negative) / len(negative) if negative else None,
            'constraints_passed': all(row['constraints_passed'] for row in results),
            'macro_metrics': aggregate, 'cases': results,
            'notice': '质量指标基于提供的独立标注。未知候选按等级0计算并单列，空结果案例单独统计。'
                      '现场调用、标注人员资格、材料代表性与真实模型语义继续依据对应证据核验。'}
