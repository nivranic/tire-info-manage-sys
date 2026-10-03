"""Keep known conflict boundaries without copying unselected source content to AI."""
from sqlalchemy import select

from .field_authority import canonical_field, known_values_differ
from .knowledge_index import CONFLICT_FIELDS, IDENTITY_FIELDS, refresh_index
from .knowledge_models import KnowledgeDocument
from .service import QueryService


def unselected_conflicts(db, registry, selected):
    if not selected:
        return [], False
    QueryService(db, None).lock_ingestion()
    refresh_index(db, registry)
    variants = {row['id'] for row, _source in selected}
    documents = db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.variant_id.in_(variants))).all()
    warnings, has_private = [], False
    for variant_id in sorted(variants):
        selections = [(row, source) for row, source in selected if row['id'] == variant_id]
        selected_observations = {(source, row.get('snapshot_id')) for row, source in selections}
        conflicted = False
        for document in documents:
            observation = (document.source_id, document.payload['reference'].get('snapshot_id'))
            if document.variant_id != variant_id or observation in selected_observations:
                continue
            other = {}
            for key, value in document.payload['_values'].items():
                if key in CONFLICT_FIELDS:
                    other.setdefault(canonical_field(key), []).append(value)
            for row, _source in selections:
                values = {**row.get('facts', {}), **{key: row.get(key) for key in IDENTITY_FIELDS}}
                if any(key in CONFLICT_FIELDS and canonical_field(key) in other
                       and any(known_values_differ([value, other_value]) for other_value in other[canonical_field(key)])
                       for key, value in values.items()):
                    conflicted = True
                    has_private |= document.payload['privacy_class'] != 'public'
        if conflicted:
            # Even the existence of private outside evidence makes the pack private.
            # Do not include its values, URLs, identities, excerpts or record count.
            warnings.append({'variant_id': variant_id, 'scope': 'unselected_formal_evidence',
                'resolution': 'not_evaluated',
                'notice': '所选版本另有未选入的正式历史证据与本包取值不同。其内容未外发；请回到知识检索补充核对，不能据本包认定来源已达成一致。'})
    return warnings, has_private
