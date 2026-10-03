"""Deterministic semantic text: source facts, never observation or request identities."""
from fastapi import HTTPException

from .domain import digest, stable_json

TEXT_CONTRACT = 'tire-structured-semantic@1'
OMIT_KEYS = {'id', 'snapshot_id', 'variant_id', 'event_id', 'event_revision', 'revision', 'revision_id',
             'observed_at', 'verified_at', 'created_at', 'recorded_at', 'source_updated_at',
             'source_url', 'url', 'source_id', 'source_version', 'evidence_locator', 'evidence_spans',
             'operator', 'actor_session_id', 'rights_basis', 'raw_hash', 'body', 'raw_body',
             'source_description', 'source_field_conflicts', 'matched_tire_variant_id'}


def semantic_values(value):
    if isinstance(value, dict):
        return {key: semantic_values(item) for key, item in value.items()
                if key not in OMIT_KEYS and not key.endswith('_id') and not key.endswith('_ids')}
    if isinstance(value, list):
        return [semantic_values(item) for item in value]
    return value


def chunk_text(value):
    result, characters, size = [], [], 0
    for char in value:
        width = len(char.encode('utf-8'))
        if size + width > 6000:
            result.append(''.join(characters))
            characters, size = [], 0
        characters.append(char)
        size += width
    if characters:
        result.append(''.join(characters))
    return result


def document_chunks(document, config):
    data = document.payload
    content = stable_json({'kind': data['kind'], 'label': data['label'], 'values': semantic_values(data['_values'])})
    chunks = []
    for value in chunk_text(content):
        text_hash = digest(value)
        cache_id = digest({'provider': 'openai_embeddings', 'model': config.model, 'dimensions': config.dimensions,
            'text_contract': TEXT_CONTRACT, 'privacy_class': data['privacy_class'], 'text_hash': text_hash})
        chunks.append({'text': value, 'hash': text_hash, 'cache_id': cache_id, 'privacy_class': data['privacy_class']})
    return chunks


def bounded_batch(chunks):
    if len(chunks) > 32 or sum(len(item['text'].encode('utf-8')) for item in chunks) > 100000:
        raise HTTPException(422, '本次语义材料超过 32 个分块或 100 KB，请缩小所选文档；不会静默截断')
