"""Private synthetic API for interest-following browser QA; never start the normal DB.

All producer operations call production services against an isolated SQLite store.
External networking, provider calls and parser children are forbidden in this process.
"""
import argparse
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import platform
import socket
import sys


ROOT = Path(__file__).resolve().parents[1]


def serve(port: int, web_port: int, output: Path, *, governance: bool = False, applicability: bool = False):
    governance = governance or applicability
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve())
    assert 1024 <= port <= 65535 and port not in {3000, 8000}
    assert 1024 <= web_port <= 65535 and web_port not in {3000, 8000, port}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True, exist_ok=False)
    storage = output / 'storage'
    storage.mkdir()
    database_path = storage / 'synthetic.sqlite'
    for name in list(os.environ):
        if name.startswith('TI_') or name in {'TIRE_DATABASE_URL', 'DATABASE_URL', 'TIRE_CORS_ORIGINS'}:
            del os.environ[name]
    os.environ.update(
        TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_LOGS='0',
        TI_OBJECT_STORE_ROOT=str(storage / 'objects'), TI_OBJECT_STORE_BACKEND='filesystem',
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}',
    )
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    platform.uname()  # Prewarm Windows' lazy subprocess before fencing children.
    counters = {'external_network_attempts': 0, 'parser_children': 0, 'provider_calls': 0,
                'normal_database_attempts': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['parser_children'] += 1
            raise RuntimeError('Parser children forbidden in private interest QA')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External networking forbidden in private interest QA')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counters['normal_database_attempts'] += 1
                raise RuntimeError('private_database_required')
    sys.addaudithook(audit)

    import uvicorn
    from fastapi import HTTPException, Query, Request
    from sqlalchemy import func, select
    from tire_api.db import FactVersion, Snapshot, TireVariant, UserSession, uid, utcnow
    from tire_api.domain import LiveQueryRequest
    from tire_api.main import create_app
    from tire_api.service import QueryService
    from tire_api.test_events import EventPayload, TireTestEvent, TireTestRevision, append
    from test_core import FixtureRegistry, QUERY, VARIANT, success
    from test_fitment_relations import seed_vehicle, vehicle_payload
    from test_test_events import PAYLOAD

    class SyntheticRegistry(FixtureRegistry):
        supports_parser_deployments = False

    registry = SyntheticRegistry()
    values = {'265/40ZR20': 300, '265/40R20': 300}
    depths = {size: 7 for size in values}
    included = set(values)
    source_marker = 0

    def tire_result():
        rows = [{**deepcopy(VARIANT), 'size': size, 'manufacturer_product_code': 'SYN-' + size,
                 'acoustic_technology': 'Acoustic', 'facts': {'utqg_treadwear': value,
                     **({'product_code_type': 'MSPN', 'tread_depth': {'value': depths[size], 'unit': 'mm'}} if applicability else {})}}
                for size, value in values.items() if size in included]
        if governance:
            # Four in-query rows permit a one-row removal below the quality gate.
            # Different control brands keep them outside the exact target AND.
            rows.extend({**deepcopy(VARIANT), 'size': '265/40R20', 'brand': 'Control Fixture Brand',
                         'manufacturer_product_code': f'SYN-CONTROL-{index}',
                         'facts': {'utqg_treadwear': 300, **({'product_code_type': 'MSPN'} if applicability else {})}} for index in range(2))
        body = {'values': values, 'present': sorted(included)} if governance else values
        if applicability:
            body = {**body, 'depths': depths, 'source_marker': source_marker}
        return success('Synthetic interest evidence ' + json.dumps(body, sort_keys=True), rows)

    registry.result = tire_result()
    app = create_app('sqlite:///' + database_path.as_posix(), registry)
    original_lifespan = app.router.lifespan_context
    state = {'normal_database_used': False, 'synthetic_only': True, 'tire_operations': 0,
             'governance_qa_enabled': governance, 'applicability_qa_enabled': applicability}

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            with application.state.database.sessions() as db:
                seed = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=2))
                db.add(seed)
                db.commit()
                seed_id = seed.id
                seeded = await QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate(QUERY), seed_id)
                if governance and (seeded['data_state'] != 'live' or len(seeded['variants']) != 4):
                    raise RuntimeError('Synthetic governance seed rejected: ' + str(seeded.get('reason')))
            with application.state.database.sessions() as db:
                item = TireTestEvent(id=uid())
                db.add(item)
                db.flush()
                payload = EventPayload.model_validate(deepcopy(PAYLOAD['event'])).model_dump(mode='json')
                row = append(db, item.id, payload, 'create', 'active',
                             'Synthetic QA', 'Project-authored synthetic browser fixture', seed_id, 1)
                state['test_event_id'] = row['id']
            vehicle = vehicle_payload()
            vehicle['vehicle']['region'] = 'US'  # Match the synthetic tire region; never bypass the production gate.
            state['vehicle_snapshot_id'] = seed_vehicle(application.state.database, seed_id, vehicle)
            state['vehicle_id'] = 'synthetic-vehicle-gen1'
            (output / 'fixture-start.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'port': port, **state}), flush=True)
            yield
            with application.state.database.sessions() as db:
                from tire_api.interest_models import Interest, InterestRevision, InterestEvent, InterestNotification
                models = [Interest, InterestRevision, InterestEvent, InterestNotification]
                if governance:
                    from tire_api.interest_catalog_models import TireCatalogRevision
                    models.append(TireCatalogRevision)
                if applicability:
                    from tire_api.interest_applicability_models import TireCurationApplicabilityEvent
                    from tire_api.db import ManualFactRevision
                    models.extend([TireCurationApplicabilityEvent, ManualFactRevision])
                state['counts'] = {model.__name__: db.scalar(select(func.count()).select_from(model))
                                   for model in models}
            (output / 'fixture-final.json').write_text(json.dumps({**state, **counters}, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def current_state():
        metadata = {}
        if governance:
            with app.state.database.sessions() as db:
                variants = []
                for variant in db.scalars(select(TireVariant).order_by(TireVariant.id)):
                    fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant.id)
                                     .order_by(FactVersion.version.desc()).limit(1))
                    variants.append({'id': variant.id, 'identity': variant.identity,
                                     'fact_id': fact.id if fact else None,
                                     'snapshot_id': fact.snapshot_id if fact else None})
                metadata = {'variants': variants, 'catalog_present_sizes': sorted(included)}
        return {**state, **counters, 'values': values, **metadata}

    if governance:
        @app.post('/fixture/catalog')
        async def change_catalog(request: Request, size: str = Query('265/40R20'),
                                 present: bool = Query(True), verify_only: bool = Query(False)):
            if size not in values:
                raise HTTPException(422, 'Unknown synthetic size')
            if verify_only:
                registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                                   'etag': '"fixture-etag"'}
            else:
                if present:
                    included.add(size)
                else:
                    included.discard(size)
                registry.result = tire_result()
            with app.state.database.sessions() as db:
                result = await QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate({**QUERY, 'fallback_policy': 'never'}),
                                                                 request.state.session_id)
            state['tire_operations'] += 1
            return result

    if applicability:
        @app.post('/fixture/applicability/source')
        async def change_applicability_source(request: Request, value: int | None = Query(None, ge=0, le=999),
                                              depth: int | None = Query(None, ge=1, le=20),
                                              scope: str = Query('a', pattern='^(a|b)$'),
                                              verify_only: bool = Query(False), raw_only: bool = Query(False)):
            nonlocal source_marker
            if verify_only and (value is not None or depth is not None or raw_only):
                raise HTTPException(422, 'Verification must not edit synthetic source inputs')
            if verify_only:
                registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                                   'etag': '"fixture-etag"'}
            else:
                if value is not None:
                    values['265/40R20'] = value
                if depth is not None:
                    depths['265/40R20'] = depth
                if raw_only:
                    source_marker += 1
                registry.result = tire_result()
            query = deepcopy(QUERY['query'])
            if scope == 'b':
                query.pop('model')
            with app.state.database.sessions() as db:
                result = await QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate({
                    'query': query, 'fallback_policy': 'never'}), request.state.session_id)
            state['tire_operations'] += 1
            return result

    @app.post('/fixture/tire')
    async def change_tire(request: Request, value: int = Query(..., ge=0, le=999),
                          size: str = Query('265/40ZR20')):
        if size not in values:
            raise HTTPException(422, 'Unknown synthetic size')
        values[size] = value
        registry.result = tire_result()
        with app.state.database.sessions() as db:
            result = await QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate(QUERY),
                                                             request.state.session_id)
        state['tire_operations'] += 1
        return result

    @app.post('/fixture/test')
    def change_test(request: Request, action: str = Query('revise', pattern='^(revise|revoke|restore)$')):
        with app.state.database.sessions() as db:
            QueryService(db, None).lock_ingestion()
            old = db.scalar(select(TireTestRevision).where(TireTestRevision.event_id == state['test_event_id'])
                            .order_by(TireTestRevision.revision.desc()).limit(1))
            payload = deepcopy(old.payload)
            if action == 'revise':
                payload['measurements'][0]['raw_value'] = str(38 + old.revision)
                payload['measurements'][0]['evidence_span'] = 'Synthetic revised wet braking value'
            return append(db, old.event_id, payload, action, 'revoked' if action == 'revoke' else 'active',
                          'Synthetic QA', 'Project-authored synthetic revision', request.state.session_id,
                          old.revision + 1)

    @app.post('/fixture/relation')
    def change_relation(request: Request, action: str = Query('create', pattern='^(create|review|revoke)$')):
        from tire_api.fitment_relations import RelationDecision, RelationPreviewRequest, append_revision, preview
        from tire_api.fitment_relation_models import FitmentRelationRevision
        from uuid import uuid4
        with app.state.database.sessions() as db:
            relation_id = state.get('relation_id')
            if action == 'create':
                if relation_id:
                    raise HTTPException(409, 'Synthetic relation already exists')
                variant = next(row for row in db.scalars(select(TireVariant)) if row.identity['size'] == '265/40R20'
                               and (not governance or row.identity['brand'] == 'Fixture Brand'))
                fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant.id)
                                 .order_by(FactVersion.version.desc()).limit(1))
                snapshot = db.get(Snapshot, fact.snapshot_id)
                selection = {'vehicle_id': state['vehicle_id'], 'vehicle_snapshot_id': state['vehicle_snapshot_id'],
                             'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'rear',
                             'variant_id': variant.id, 'tire_snapshot_id': snapshot.id, 'fact_version_id': fact.id}
            else:
                old = db.scalar(select(FitmentRelationRevision).where(FitmentRelationRevision.relation_id == relation_id)
                                .order_by(FitmentRelationRevision.revision.desc()).limit(1))
                if old is None:
                    raise HTTPException(409, 'Create the synthetic relation first')
                selection = old.selection
            raw = {'mode': 'history', 'action': action, 'relation_id': relation_id, 'selection': selection}
            proposed = preview(db, RelationPreviewRequest.model_validate(raw))
            decision = RelationDecision.model_validate({**raw, 'expected_revision': proposed['revision'],
                'expected_fingerprint': proposed['fingerprint'], 'operator': 'Synthetic QA',
                'reason': 'Project-authored synthetic manual relation; not official OE',
                'acknowledged': True, 'acknowledge_unknowns': True})
            result = append_revision(db, decision, request.state.session_id, str(uuid4()))
            state['relation_id'] = result['relation']['id']
            return result

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'shutdown_requested': True}

    server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--web-port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--governance', action='store_true', help='Enable synthetic catalog transitions for governance QA')
    parser.add_argument('--applicability', action='store_true', help='Enable typed cross-query source facts for applicability QA')
    options = parser.parse_args()
    serve(options.port, options.web_port, options.output, governance=options.governance or options.applicability,
          applicability=options.applicability)
