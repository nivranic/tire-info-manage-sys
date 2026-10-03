"""Explicit historical field review views; no field decision or fact writes."""
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select

from .db import TireVariant
from .field_authority import canonical_field, policy_catalog, policy_descriptor, resolve_fields
from .field_evidence import accepted_variant_candidates, complete_missing_candidates, variant_field_resolution

NOTICE = '正式历史证据的字段默认展示与冲突；不代表当前库存，不修改来源事实、人工纠错或身份。'


def register_field_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/field-policies')
    def policies():
        return policy_catalog()

    @app.get('/v1/tire-variants/{variant_id}/field-resolution')
    def detail(variant_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        if db.get(TireVariant, variant_id) is None:
            raise HTTPException(404, '未找到精确轮胎版本')
        return variant_field_resolution(db, app.state.registry, variant_id)

    @app.get('/v1/field-conflicts')
    def listing(mode: Literal['history'] = Query(...), field: str | None = Query(None, max_length=80),
                source_id: str | None = Query(None, max_length=80), offset: int = Query(0, ge=0, le=100000),
                limit: int = Query(20, ge=1, le=100), db=Depends(get_db)):
        if field is not None and field not in {row['field'] for row in policy_catalog()['fields']}:
            raise HTTPException(422, '请选择字段目录中的字段')
        if source_id is not None and source_id not in {row['id'] for row in app.state.registry.sources()}:
            raise HTTPException(422, '请选择已登记的来源')
        ids = db.scalars(select(TireVariant.id).order_by(TireVariant.id)).all()
        groups = accepted_variant_candidates(db, app.state.registry, ids)
        resolutions = []
        for variant_id, candidates in groups.items():
            resolution = resolve_fields(complete_missing_candidates(candidates), variant_id=variant_id, scope='history')
            conflicts = [row for row in resolution['fields'] if row['state'] in {'conflict_preferred', 'conflict_tied'}
                         and (field is None or row['field'] == canonical_field(field))]
            # Filtering selects conflicts involving a source. All competing values
            # remain visible; filtering must not make the disagreement disappear.
            if conflicts and (source_id is None or any(item['source_id'] == source_id
                              for row in conflicts for item in row['candidates'])):
                resolutions.append(resolution)
        resolutions.sort(key=lambda row: row['variant_id'])
        return {'policy': policy_descriptor(), 'scope': 'history', 'data_state': 'local_snapshot',
            'items': resolutions[offset:offset + limit], 'offset': offset, 'limit': limit, 'total': len(resolutions),
            'filters': {'field': field, 'source_id': source_id}, 'notice': NOTICE}
