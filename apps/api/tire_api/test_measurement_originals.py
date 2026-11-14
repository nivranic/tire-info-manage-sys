"""Exact saved-PDF quotations for manually transcribed test measurements."""
from fastapi import HTTPException
import re

from .document_text_contract import DocumentTextReference

POLICY = 'test-pdf-original@1'


def fail(code='test_measurement_pdf_reference_invalid', status=409):
    raise HTTPException(status, {'code': code,
        'message': '成绩的PDF引用或短摘录未能从保存原件核对，请重新选择原件区间并保留原文。'})


def measurement_sources(payload):
    result = []
    for value in payload['measurements']:
        if value.get('pdf_reference') is not None:
            reference = DocumentTextReference.model_validate(value['pdf_reference'])
            result.append((reference, value['evidence_span']))
    return result


def check_measurement_sources(db, payload):
    # Lazy imports keep the event/retrieval module graph acyclic. One extraction
    # per original serves all selected quotations in this operation.
    from .text_embeddings import DocumentSelection, original_excerpt
    pdfs, documents = {}, {}
    for reference, quote in measurement_sources(payload):
        try:
            excerpt = original_excerpt(db, DocumentSelection(kind='document_text', reference=reference), pdfs)
        except HTTPException:
            fail()
        if quote not in excerpt['text']:
            fail('test_measurement_pdf_quote_mismatch')
        documents[reference.document_id] = (excerpt['document'], reference.document_fingerprint)
    return documents


def recheck_documents(db, documents):
    from .document_text import checked_document
    for identity, (metadata, fingerprint) in documents.items():
        try:
            _row, _raw, current, current_fingerprint = checked_document(db, identity)
        except HTTPException:
            fail()
        if current != metadata or current_fingerprint != fingerprint:
            fail('test_measurement_pdf_original_changed')


def pdf_fact_items(payload, *, require_policy=True):
    """Pure validation of the measurement-to-original contract in frozen packs."""
    from .domain import stable_json
    from .test_events import Measurement
    candidates = [fact for fact in payload.get('facts', [])
        if isinstance(fact, dict) and isinstance(fact.get('value'), dict) and 'pdf_reference' in fact['value']]
    if not candidates:
        if require_policy and payload.get('test_pdf_policy') is not None:
            raise ValueError('test_pdf_policy_mismatch')
        return []
    evidence = {item['id']: item for item in payload.get('evidence', [])}
    result = []
    for fact in candidates:
        value = fact['value']
        source = evidence[fact['evidence_id']]
        ordinal = re.fullmatch(r'本场成绩 ([1-9][0-9]{0,3})', fact['field'])
        raw = {key: item for key, item in value.items() if key not in {'参测胎', '指标与条件'}}
        measured = Measurement.model_validate(raw)
        if (not str(source.get('kind', '')).startswith('manual_test_') or not source.get('event_id')
                or type(source.get('revision')) is not int or source['revision'] < 1
                or not ordinal or int(ordinal[1]) > 1000 or measured.pdf_reference is None
                or measured.model_dump(mode='json') != raw
                or fact['field_code'] != source['kind'] + '.field_' + str(int(ordinal[1]) + 7)
                or fact['text'] != source['label'] + '：' + fact['field'] + ' = ' + stable_json(value)):
            raise ValueError('test_pdf_frozen_measurement_invalid')
        result.append((source, fact, measured.pdf_reference, measured.evidence_span))
    if require_policy and (bool(result) != (payload.get('test_pdf_policy') == POLICY)
            or not result and payload.get('test_pdf_policy') is not None):
        raise ValueError('test_pdf_policy_mismatch')
    return result


def check_frozen_measurement(db, source, fact):
    from .domain import digest
    from .service import timestamp
    from .test_events import latest
    try:
        row = latest(db, source['event_id'], source['revision'])
        if row.state == 'revoked' or digest(row.payload) != row.fingerprint:
            fail()
        ordinal = int(fact['field'].removeprefix('本场成绩 ')) - 1
        measured = row.payload['measurements'][ordinal]
        person = next(item for item in row.payload['participants'] if item['key'] == measured['participant_key'])
        metric = next(item for item in row.payload['metrics'] if item['key'] == measured['metric_key'])
        expected = {'参测胎': person, '指标与条件': metric, **measured}
        if (fact['value'] != expected or source['source_url'] != row.payload['source_url']
                or source['kind'] != 'manual_test_' + row.payload['relationship']
                or source['label'] != '人工记录 · ' + row.payload['title']
                or source['data_state'] != 'local_snapshot'
                or source['observed_at'] != timestamp(row.created_at)
                or source['verification_status'] != 'unverified' or source['verified_at'] is not None):
            fail()
    except (IndexError, KeyError, TypeError, ValueError, StopIteration):
        fail()
