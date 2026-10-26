"""Private raw/provenance boundaries; receipts are synthetic, never PDF child proof.

The one historical S2 input is read only from the explicit reviewed path, pinned
before use, and stored in this run's private ObjectStore. It is not a Git fixture.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from sqlalchemy import select

from tire_api import parser_bundles as bundles, parser_runtime as runtime
from tire_api import vehicle_raw as raw
from tire_api.db import (CaptureObject, Database, EvidenceObject, QueryRun, RawCapture,
                         RejectedObservation, UserSession, uid, utcnow)
from tire_api.documents import record_object
from tire_api.parser_release_models import (ParserBundle, ParserDeploymentRevision,
                                            ParserExecution, ParserSelection)
from tire_api.parser_releases import record_execution
from tire_api.vehicles import (VehicleManufacturer, VehicleModel, VehicleQuarantine,
                               VehicleSnapshot, fitment_fact_hash, vehicle_provenance)

SOURCE = 'xiaomi-cn-vehicles'
VEHICLE = 'xiaomi-su7-first-generation'
CURRENT = 'xiaomi-su7-current'
URL = ('https://s1.xiaomiev.com/activity-outer-assets/0328/env/'
       'SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf')
JSON_URL = 'https://website-api.xiaomiev.com/mtop/guidemarketing/product/pc/paramComparison'
METHOD = 'sha256_bound_reviewed_mapping'
MAPPING = 'xiaomi-su7-first-generation-pdf@1'
S2_SHA = '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f'
S2_SIZE = 3240150
S2_PATH = (Path(__file__).resolve().parents[3] / '.artifacts'
    / 'r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f' / 'xiaomi-first-generation-2.pdf')
MAPPING_FILE = 'adapters/xiaomi_first_generation_pdf.py'
UNKNOWN = b'%PDF-1.7\n%r86-synthetic-unreviewed-\x80\n%%EOF\n'
META_KEYS = {'evidence_format', 'body_encoding', 'body', 'raw_capture_id', 'raw_hash',
             'byte_count', 'content_type', 'content_path', 'parse_method', 'mapping_id'}
PROVENANCE_KEYS = {'contract', 'method', 'mapping_id', 'source_raw_hash', 'bundle_id', 'mapping_file_sha256'}


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def rejected(call):
    with pytest.raises(raw.VehicleRawIntegrityError) as error:
        call()
    assert error.value.code == 'vehicle_raw_integrity_failed'


@pytest.fixture
def private(tmp_path_factory, monkeypatch):
    root = tmp_path_factory.mktemp('vr')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(root / 'o'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(root / 'b'))
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    database = Database('sqlite:///' + (root / 'p.db').as_posix())
    database.initialize()
    with database.sessions() as db:
        db.add(UserSession(id='r86-session', expires_at=utcnow() + timedelta(days=1)))
        db.add(VehicleManufacturer(id='xiaomi', name='Synthetic private manufacturer'))
        db.flush()
        for vehicle in (VEHICLE, CURRENT):
            db.add(VehicleModel(id=vehicle, manufacturer_id='xiaomi', name='Synthetic private vehicle',
                generation='synthetic', region='CN', source_vehicle_id=vehicle))
        db.commit()
    context = SimpleNamespace(root=root, database=database)
    manifest, _ = seal(context, monkeypatch)
    descriptor = runtime.descriptor_for_manifest(manifest, SOURCE)
    with database.sessions() as db:
        db.add(ParserBundle(id=manifest['bundle_id'], manifest=deepcopy(manifest),
            descriptors={SOURCE: deepcopy(descriptor)}, operator='Synthetic R86',
            reason='Private original storage pin; no Parser execution', origin='r86-private'))
        db.flush()
        db.add(ParserDeploymentRevision(id='r86-storage-deployment', source_id=SOURCE, revision=1,
            state='active', bundle_id=manifest['bundle_id'], descriptor=deepcopy(descriptor),
            action='bootstrap', actor_session_id='r86-session', idempotency_key=uid(),
            request_hash='1' * 64, operator='Synthetic R86', reason='Private original storage pin'))
        db.commit()
    try:
        yield context
    finally:
        database.close()


@pytest.fixture
def s2_bytes():
    if not S2_PATH.is_file():
        pytest.skip('reviewed historical S2 PDF is not included in a public clone')
    value = S2_PATH.read_bytes()
    assert len(value) == S2_SIZE and hashlib.sha256(value).hexdigest() == S2_SHA
    return value


def new_run(db, *, vehicle=VEHICLE, query=None, source=SOURCE, pinned=True):
    query = {'vehicle_id': vehicle} if query is None else query
    row = QueryRun(id=uid(), session_id='r86-session', source_id=source,
                   query=query, query_key=digest(query), fallback_policy='never')
    db.add(row)
    db.flush()
    if pinned and vehicle == VEHICLE and source == SOURCE:
        deployment = db.get(ParserDeploymentRevision, 'r86-storage-deployment')
        db.add(ParserSelection(query_run_id=row.id, source_id=SOURCE, deployment_id=deployment.id,
            bundle_id=deployment.bundle_id, deployment_revision=deployment.revision,
            descriptor=deepcopy(deployment.descriptor)))
        db.flush()
    return row


def observation(data, *, identity=None, parser='r86-synthetic@1', binary=True):
    return {'body': data if binary else data.decode('utf-8', errors='strict'),
        'body_encoding': 'binary' if binary else 'utf-8', 'url': URL if binary else JSON_URL,
        'content_type': 'application/pdf' if binary else 'application/json',
        'parser_version': parser, 'parser_identity': identity}


def capture(db, run, data=UNKNOWN, *, observed=None, mapped=True):
    if observed is None:
        selected = db.get(ParserSelection, run.id)
        identity = {'bundle_id': selected.bundle_id, 'parser_digest': selected.descriptor['parser_digest'],
            'deployment_revision': selected.deployment_revision} if selected else None
        observed = observation(data, identity=identity,
            parser=selected.descriptor['parser_version'] if selected else 'r86-synthetic@1')
    row = RawCapture(id=uid(), query_id=run.id, source_id=run.source_id, query_key=run.query_key,
        target_kind='vehicle', source_url=observed['url'], raw_hash=hashlib.sha256(data).hexdigest(),
        raw_body=data, byte_count=len(data), content_type=observed['content_type'],
        body_encoding=observed['body_encoding'], parser_version=observed['parser_version'],
        parser_identity=observed['parser_identity'])
    db.add(row)
    db.flush()
    if mapped:
        saved = record_object(db, data)
        db.add(CaptureObject(capture_id=row.id, raw_hash=saved))
        db.flush()
    return row


def payload(mapping=MAPPING):
    return {'vehicle': {'id': VEHICLE, 'source_version': 'pdf-sha256:' + S2_SHA},
        'trims': [], 'fitments': [], 'footnotes': [], 'parse_method': METHOD, 'mapping_id': mapping}


def snapshot(db, cap=None, *, provenance=None, row_id=None):
    binary = cap is not None and cap.body_encoding == 'binary'
    document = payload(provenance['mapping_id'] if provenance else MAPPING)
    if provenance is not None:
        document['parse_provenance'] = deepcopy(provenance)
    text = '{"synthetic":"旧原文，不规范化"}'
    row = VehicleSnapshot(id=row_id or uid(), vehicle_id=VEHICLE if binary else CURRENT,
        source_id=SOURCE, source_url=cap.source_url if cap else JSON_URL,
        raw_hash=cap.raw_hash if cap else hashlib.sha256(text.encode('utf-8')).hexdigest(),
        body=None if binary else cap.raw_body.decode('utf-8') if cap else text,
        body_encoding='binary' if binary else 'utf-8', raw_capture_id=cap.id if cap else None,
        content_type=cap.content_type if cap else 'application/json',
        parser_version=cap.parser_version if cap else 'r86-legacy@1',
        parser_identity=cap.parser_identity if cap else None,
        payload=document, fact_hash=fitment_fact_hash(document), fact_version=1)
    db.add(row)
    db.flush()
    return row


def quarantine(db, cap, provenance):
    baseline = snapshot(db)
    document = payload(provenance['mapping_id'])
    document['parse_provenance'] = deepcopy(provenance)
    row = VehicleQuarantine(id=uid(), query_id=cap.query_id, vehicle_id=VEHICLE, source_id=SOURCE,
        previous_snapshot_id=baseline.id, source_url=cap.source_url, raw_hash=cap.raw_hash,
        body=None, body_encoding='binary', raw_capture_id=cap.id, content_type='application/pdf',
        parser_version=cap.parser_version, parser_identity=cap.parser_identity,
        payload=document, quality={'reason_codes': ['row_loss_threshold']})
    db.add(row)
    db.flush()
    return row


def mapping_source(mapping):
    return ("PARSE_METHOD = 'sha256_bound_reviewed_mapping'\n"
        + 'MAPPING_ID = ' + repr(mapping) + '\n'
        + 'REVIEWED_RAW_SHA256 = ' + repr(S2_SHA) + '\n'
        + 'REVIEWED_BYTE_COUNT = 3240150\n'
        + "raise RuntimeError('r86-archived-mapping-must-never-execute')\n").encode('utf-8')


def seal(private, monkeypatch, mapping=MAPPING, *, installed_mapping=False):
    source = private.root / ('si' if installed_mapping else 's' + mapping.rsplit('@', 1)[1]) / 'tire_api'
    installed = Path(runtime.__file__).parent
    for path in installed.rglob('*.py'):
        destination = source / path.relative_to(installed)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    code = (installed / MAPPING_FILE).read_bytes() if installed_mapping else mapping_source(mapping)
    if not installed_mapping:
        (source / MAPPING_FILE).write_bytes(code)
    with monkeypatch.context() as patch:
        patch.setattr(bundles, '_ROOT', source)
        manifest = bundles.seal_deployed_bundle()
    return manifest, code


def chain(private, monkeypatch, data, *, mapping=MAPPING, revision=1, installed_mapping=False):
    """A genuine private bundle/registration with a synthetic completed receipt."""
    manifest, code = seal(private, monkeypatch, mapping, installed_mapping=installed_mapping)
    descriptor = runtime.descriptor_for_manifest(manifest, SOURCE)
    with private.database.sessions() as db:
        if db.get(ParserBundle, manifest['bundle_id']) is None:
            db.add(ParserBundle(id=manifest['bundle_id'], manifest=deepcopy(manifest),
                descriptors={SOURCE: deepcopy(descriptor)}, operator='Synthetic R86',
                reason='Private helper verification; no production PDF child', origin='r86-private'))
            db.flush()
        deployment = db.scalar(select(ParserDeploymentRevision).where(
            ParserDeploymentRevision.source_id == SOURCE, ParserDeploymentRevision.revision == revision))
        if deployment is None:
            deployment = ParserDeploymentRevision(id=uid(), source_id=SOURCE, revision=revision,
                state='active', bundle_id=manifest['bundle_id'], descriptor=deepcopy(descriptor),
                action='bootstrap', actor_session_id='r86-session', idempotency_key=uid(),
                request_hash='1' * 64, operator='Synthetic R86', reason='Private helper verification')
            db.add(deployment)
        assert deployment.bundle_id == manifest['bundle_id']
        run = new_run(db, pinned=False)
        identity = {'bundle_id': manifest['bundle_id'], 'parser_digest': descriptor['parser_digest'],
                    'deployment_revision': revision}
        observed = observation(data, identity=identity, parser=descriptor['parser_version'])
        cap = capture(db, run, data, observed=observed)
        db.add(ParserSelection(query_run_id=run.id, source_id=SOURCE, deployment_id=deployment.id,
            bundle_id=manifest['bundle_id'], deployment_revision=revision, descriptor=deepcopy(descriptor)))
        db.flush()
        receipt = {'run_id': uid().replace('-', ''), 'source_id': SOURCE,
            'parser_version': descriptor['parser_version'], 'parser_digest': descriptor['parser_digest'],
            'bundle_id': manifest['bundle_id'], 'deployment_revision': revision,
            'execution_digest': descriptor['execution_digest'], 'exit_code': 0, 'reaped': True}
        receipt['input_hash'] = digest({key: receipt[key] for key in ('run_id', 'source_id',
            'parser_version', 'parser_digest', 'bundle_id', 'execution_digest', 'deployment_revision')}
            | {'query': run.query, 'raw_sha256': cap.raw_hash})
        record_execution(db, run.id, {'state': 'completed', 'receipt': receipt})
        db.commit()
        selected = {'query_run_id': run.id, 'source_id': SOURCE, **identity,
            'parser_version': descriptor['parser_version'], 'execution_digest': descriptor['execution_digest'],
            'bundle_manifest': deepcopy(manifest)}
        observed['parser_receipt'] = deepcopy(receipt)
        expected = {'contract': 'vehicle-pdf-parse@1', 'method': METHOD, 'mapping_id': mapping,
            'source_raw_hash': hashlib.sha256(data).hexdigest(), 'bundle_id': manifest['bundle_id'],
            'mapping_file_sha256': hashlib.sha256(code).hexdigest()}
        return SimpleNamespace(run_id=run.id, capture_id=cap.id, observed=observed,
            selection=selected, expected=expected, manifest=manifest, mapping_code=code)


def metadata_expected(row, data, *, method=None, mapping=None, capture_id=None):
    binary = row.body_encoding == 'binary'
    route = '/v1/captures/' if isinstance(row, RawCapture) else '/v1/vehicle-evidence/' if isinstance(row, VehicleSnapshot) else '/v1/quarantines/'
    return {'evidence_format': 'raw-evidence-v2', 'body_encoding': row.body_encoding,
        'body': None if binary else data.decode('utf-8', errors='strict'),
        'raw_capture_id': row.id if isinstance(row, RawCapture) else getattr(row, 'raw_capture_id', capture_id),
        'raw_hash': hashlib.sha256(data).hexdigest(), 'byte_count': len(data),
        'content_type': row.content_type, 'content_path': route + quote(row.id, safe='') + '/content?mode=history' if binary else None,
        'parse_method': method, 'mapping_id': mapping}


def test_unknown_binary_capture_has_authoritative_bytes_but_no_parse_success(private):
    with private.database.sessions() as db:
        run = new_run(db)
        cap = capture(db, run)
        observed = observation(UNKNOWN, identity=cap.parser_identity, parser=cap.parser_version)
        db.commit()
        assert raw.checked_vehicle_capture(db, run, observed).id == cap.id
        actual = raw.vehicle_raw_metadata(db, cap)
        assert set(actual) == META_KEYS and actual == metadata_expected(cap, UNKNOWN)
        assert db.scalar(select(VehicleSnapshot.id)) is None
        assert db.get(ParserExecution, run.id) is None


@pytest.mark.parametrize('mutation', ['source', 'query-extra', 'query-vehicle', 'query-key', 'target', 'url', 'mime', 'hash', 'encoding'])
def test_capture_source_query_and_observation_identity_are_exact(private, mutation):
    with private.database.sessions() as db:
        run = new_run(db)
        cap = capture(db, run)
        observed = observation(UNKNOWN, identity=cap.parser_identity, parser=cap.parser_version)
        db.commit()
        # Mutate transient caller values or query identity; do not disable SQL checks.
        if mutation == 'source':
            run.source_id = 'other-source'
        elif mutation == 'query-extra':
            run.query = {'vehicle_id': VEHICLE, 'unexpected': True}
            run.query_key = digest(run.query)
        elif mutation == 'query-vehicle':
            run.query = {'vehicle_id': CURRENT}
            run.query_key = digest(run.query)
        elif mutation == 'query-key':
            run.query_key = '0' * 64
        elif mutation == 'target':
            cap.target_kind = 'tire'
        elif mutation == 'url':
            observed['url'] = URL + '?alternate=1'
        elif mutation == 'mime':
            observed['content_type'] = 'application/octet-stream'
        elif mutation == 'hash':
            observed['body'] = UNKNOWN[:-1] + b'X'
        else:
            observed['body_encoding'] = 'utf-8'
        with db.no_autoflush:
            rejected(lambda: raw.checked_vehicle_capture(db, run, observed))
        db.rollback()


@pytest.mark.parametrize('damage', ['no-reference', 'wrong-reference', 'wrong-size', 'missing-file', 'same-size-bytes'])
def test_binary_object_failures_never_fall_back_to_valid_database_copy(private, damage):
    database = private.database
    with database.sessions() as db:
        run = new_run(db)
        cap = capture(db, run)
        db.commit()
        assert cap.raw_body == UNKNOWN
        if damage == 'no-reference':
            db.execute(CaptureObject.__table__.delete().where(CaptureObject.capture_id == cap.id))
        elif damage == 'wrong-reference':
            other = record_object(db, b'%PDF-other-object')
            db.execute(CaptureObject.__table__.update().where(CaptureObject.capture_id == cap.id).values(raw_hash=other))
        elif damage == 'wrong-size':
            db.execute(EvidenceObject.__table__.update().where(EvidenceObject.raw_hash == cap.raw_hash).values(byte_count=cap.byte_count + 1))
        elif damage == 'missing-file':
            database.object_store.path(cap.raw_hash).unlink()
        else:
            database.object_store.path(cap.raw_hash).write_bytes(b'X' * len(UNKNOWN))
        db.commit()
        db.expire_all()
        rejected(lambda: raw.checked_vehicle_capture(db, run,
            observation(UNKNOWN, identity=cap.parser_identity, parser=cap.parser_version)))
        rejected(lambda: raw.vehicle_raw_metadata(db, cap))
        assert cap.raw_body == UNKNOWN


def test_legacy_utf8_no_capture_is_strict_and_does_not_invent_identity(private):
    with private.database.sessions() as db:
        row = snapshot(db)
        db.commit()
        expected = row.body.encode('utf-8', errors='strict')
        before = deepcopy(row.payload)
        assert raw.checked_vehicle_bytes(db, row) == expected
        assert raw.checked_vehicle_parse_provenance(db, row) is None
        assert raw.vehicle_raw_metadata(db, row) == metadata_expected(row, expected)
        assert row.payload == before and row.raw_capture_id is None and row.parser_identity is None
        for body in ('', '\ud800', b'not-text', 'same type but wrong hash'):
            row.body = body
            with db.no_autoflush:
                rejected(lambda: raw.checked_vehicle_bytes(db, row))
        db.rollback()


def test_legacy_utf8_existing_reference_is_checked_and_object_failure_has_no_fallback(private):
    with private.database.sessions() as db:
        run = new_run(db, vehicle=CURRENT)
        data = '{"中文":"保留旧字节"}'.encode('utf-8')
        cap = capture(db, run, data, observed=observation(data, binary=False))
        row = snapshot(db, cap)
        db.commit()
        assert raw.checked_vehicle_bytes(db, row) == data
        private.database.object_store.path(cap.raw_hash).unlink()
        rejected(lambda: raw.checked_vehicle_bytes(db, row))


def test_legacy_utf8_capture_without_object_retains_only_its_existing_database_path(private):
    with private.database.sessions() as db:
        run = new_run(db, vehicle=CURRENT)
        data = '{"legacy":"没有对象引用"}'.encode('utf-8')
        cap = capture(db, run, data, observed=observation(data, binary=False), mapped=False)
        row = snapshot(db, cap)
        db.commit()
        assert raw.checked_vehicle_bytes(db, row) == data
        assert raw.vehicle_raw_metadata(db, cap) == metadata_expected(cap, data)


def test_legacy_rejected_without_capture_preserves_its_original_utf8_bytes(private):
    with private.database.sessions() as db:
        run = new_run(db, vehicle=CURRENT)
        data = '{"legacy":"失败原文"}'.encode('utf-8')
        row = RejectedObservation(id=uid(), query_id=run.id, source_id=SOURCE,
            query_key=run.query_key, target_kind='vehicle', stage='parser', reason='parser_failed',
            source_url=JSON_URL, raw_hash=hashlib.sha256(data).hexdigest(), raw_body=data,
            body_encoding='utf-8', content_type='application/json', parser_version='r86-legacy@1',
            parser_identity=None)
        db.add(row)
        db.commit()
        assert raw.vehicle_raw_metadata(db, row) == metadata_expected(row, data)
        assert db.scalar(select(RawCapture.id).where(RawCapture.query_id == run.id)) is None


@pytest.mark.parametrize('row_id', ['.', '..', 'id/unsafe', '中文'])
def test_metadata_rejects_path_segments_before_constructing_content_links(private, row_id):
    with private.database.sessions() as db:
        row = snapshot(db)
        db.commit()
        row.id = row_id
        with db.no_autoflush:
            rejected(lambda: raw.vehicle_raw_metadata(db, row))
        db.rollback()


def test_binary_capture_requires_its_original_parser_pin_even_without_execution(private):
    with private.database.sessions() as db:
        run = new_run(db)
        cap = capture(db, run)
        observed = observation(UNKNOWN, identity=cap.parser_identity, parser=cap.parser_version)
        db.execute(ParserSelection.__table__.delete().where(ParserSelection.query_run_id == run.id))
        db.commit()
        db.expire_all()
        rejected(lambda: raw.checked_vehicle_capture(db, run, observed))


def test_rejected_binary_matches_capture_bytes_but_never_claims_parse_success(private):
    with private.database.sessions() as db:
        run = new_run(db)
        cap = capture(db, run)
        row = RejectedObservation(id=uid(), query_id=run.id, source_id=SOURCE,
            query_key=run.query_key, target_kind='vehicle', stage='parser',
            reason='vehicle_pdf_revision_unreviewed', source_url=URL, raw_hash=cap.raw_hash,
            raw_body=UNKNOWN, body_encoding='binary', content_type='application/pdf',
            parser_version=cap.parser_version, parser_identity=deepcopy(cap.parser_identity))
        db.add(row)
        db.commit()
        assert raw.vehicle_raw_metadata(db, row) == metadata_expected(row, UNKNOWN, capture_id=cap.id)
        assert db.scalar(select(VehicleSnapshot.id)) is None
        row.raw_body = UNKNOWN[:-1] + b'X'
        with db.no_autoflush:
            rejected(lambda: raw.vehicle_raw_metadata(db, row))
        db.rollback()


@pytest.mark.parametrize('kind', ['snapshot', 'quarantine'])
def test_s2_provenance_and_metadata_are_frozen_without_mutating_payload(private, monkeypatch, s2_bytes, kind):
    proof = chain(private, monkeypatch, s2_bytes)
    with private.database.sessions() as db:
        run = db.get(QueryRun, proof.run_id)
        cap = db.get(RawCapture, proof.capture_id)
        document = payload()
        before = deepcopy((document, proof.observed, proof.selection))
        result = raw.build_vehicle_parse_provenance(db, run, proof.observed, document, parser_selection=proof.selection)
        assert set(result) == PROVENANCE_KEYS and result == proof.expected
        assert (document, proof.observed, proof.selection) == before
        row = snapshot(db, cap, provenance=result, row_id='r86-snapshot-id') if kind == 'snapshot' else quarantine(db, cap, result)
        db.commit()
        assert raw.checked_vehicle_bytes(db, row) == s2_bytes
        assert raw.checked_vehicle_parse_provenance(db, row) == proof.expected
        assert raw.vehicle_raw_metadata(db, row) == metadata_expected(row, s2_bytes, method=METHOD, mapping=MAPPING)
        assert fitment_fact_hash(document) == fitment_fact_hash({**document, 'parse_provenance': result})
        if kind == 'snapshot':
            old_keys = {'snapshot_id', 'source_id', 'source_url', 'source_page', 'parser_version',
                        'parser_identity', 'observed_at', 'raw_hash', 'evidence_path'}
            assert set(vehicle_provenance(row)) == old_keys


def test_unmodified_installed_mapping_source_is_sealed_and_read_without_execution(private, monkeypatch, s2_bytes):
    installed = (Path(runtime.__file__).parent / MAPPING_FILE).read_bytes()
    source_sha = hashlib.sha256(installed).hexdigest()
    proof = chain(private, monkeypatch, s2_bytes, revision=2, installed_mapping=True)
    assert proof.mapping_code == installed
    assert proof.manifest['files'][MAPPING_FILE] == {'sha256': source_sha, 'byte_count': len(installed)}
    with private.database.sessions() as db:
        run = db.get(QueryRun, proof.run_id)
        result = raw.build_vehicle_parse_provenance(db, run, proof.observed, payload(), parser_selection=proof.selection)
        assert set(result) == PROVENANCE_KEYS and result == proof.expected
        assert result['mapping_file_sha256'] == source_sha
        row = snapshot(db, db.get(RawCapture, proof.capture_id), provenance=result)
        db.commit()
        assert raw.checked_vehicle_bytes(db, row) == s2_bytes
        assert raw.checked_vehicle_parse_provenance(db, row) == result


def test_quarantine_cannot_borrow_same_vehicle_capture_from_another_query(private, monkeypatch, s2_bytes):
    proof = chain(private, monkeypatch, s2_bytes)
    with private.database.sessions() as db:
        row = quarantine(db, db.get(RawCapture, proof.capture_id), proof.expected)
        other_run = new_run(db)
        db.commit()
        row.query_id = other_run.id
        with db.no_autoflush:
            rejected(lambda: raw.checked_vehicle_bytes(db, row))
        db.rollback()


def test_historical_selection_keeps_its_execution_digest_when_registry_host_descriptor_differs(private, monkeypatch, s2_bytes):
    proof = chain(private, monkeypatch, s2_bytes)
    with private.database.sessions() as db:
        row = snapshot(db, db.get(RawCapture, proof.capture_id), provenance=proof.expected)
        db.commit()
        registered = db.get(ParserBundle, proof.expected['bundle_id'])
        descriptors = deepcopy(registered.descriptors)
        descriptors[SOURCE]['execution_digest'] = '7' * 64
        deployment = db.get(ParserDeploymentRevision, 'r86-storage-deployment')
        descriptor = {**deepcopy(deployment.descriptor), 'execution_digest': '8' * 64}
        # Model a bundle/registry imported under a different host than this
        # original Selection; its five stable source fields remain identical.
        db.execute(ParserBundle.__table__.update().where(ParserBundle.id == registered.id).values(descriptors=descriptors))
        db.execute(ParserDeploymentRevision.__table__.update().where(ParserDeploymentRevision.id == deployment.id).values(descriptor=descriptor))
        db.commit()
        db.expire_all()
        assert raw.checked_vehicle_parse_provenance(db, row) == proof.expected
        assert raw.checked_vehicle_bytes(db, row) == s2_bytes


@pytest.mark.parametrize('damage', ['absent', 'missing', 'extra', 'contract', 'method', 'mapping_id', 'source_raw_hash', 'bundle_id', 'mapping_file_sha256'])
def test_binary_frozen_provenance_is_closed_and_cannot_be_self_asserted(private, monkeypatch, s2_bytes, damage):
    proof = chain(private, monkeypatch, s2_bytes)
    with private.database.sessions() as db:
        cap = db.get(RawCapture, proof.capture_id)
        changed = deepcopy(proof.expected)
        if damage == 'missing':
            changed.pop('method')
        elif damage == 'extra':
            changed['caller_asserted'] = True
        else:
            changed[damage] = '0' * 64 if damage.endswith('hash') or damage.endswith('sha256') or damage == 'bundle_id' else 'forged'
        row = snapshot(db, cap, provenance=None if damage == 'absent' else changed)
        db.commit()
        rejected(lambda: raw.checked_vehicle_parse_provenance(db, row))
        rejected(lambda: raw.checked_vehicle_bytes(db, row))


@pytest.mark.parametrize('damage', ['caller-block', 'observation-block', 'mapping-declaration', 'payload-vehicle', 'payload-source', 'receipt', 'selection', 'missing-execution'])
def test_builder_requires_registered_original_selection_and_completed_receipt(private, monkeypatch, s2_bytes, damage):
    proof = chain(private, monkeypatch, s2_bytes)
    with private.database.sessions() as db:
        run = db.get(QueryRun, proof.run_id)
        document, observed, selection = payload(), deepcopy(proof.observed), deepcopy(proof.selection)
        if damage == 'caller-block':
            document['parse_provenance'] = deepcopy(proof.expected)
        elif damage == 'observation-block':
            observed['parse_provenance'] = deepcopy(proof.expected)
        elif damage == 'mapping-declaration':
            document['mapping_id'] = 'xiaomi-su7-first-generation-pdf@999'
        elif damage == 'payload-vehicle':
            document['vehicle']['id'] = CURRENT
        elif damage == 'payload-source':
            document['vehicle']['source_version'] = 'pdf-sha256:' + '0' * 64
        elif damage == 'receipt':
            observed['parser_receipt']['input_hash'] = '0' * 64
        elif damage == 'selection':
            selection['deployment_revision'] += 1
        else:
            db.execute(ParserExecution.__table__.delete().where(ParserExecution.query_run_id == run.id))
            db.flush()
        rejected(lambda: raw.build_vehicle_parse_provenance(db, run, observed, document, parser_selection=selection))
        db.rollback()


def test_unknown_revision_capture_cannot_be_promoted_by_a_synthetic_completed_receipt(private, monkeypatch):
    proof = chain(private, monkeypatch, UNKNOWN)
    with private.database.sessions() as db:
        run = db.get(QueryRun, proof.run_id)
        assert raw.checked_vehicle_capture(db, run, proof.observed).id == proof.capture_id
        rejected(lambda: raw.build_vehicle_parse_provenance(db, run, proof.observed,
            payload(), parser_selection=proof.selection))


@pytest.mark.parametrize('damage', ['missing-bundle', 'tampered-mapping'])
def test_original_bundle_is_required_and_never_rebuilt_from_workspace(private, monkeypatch, s2_bytes, damage):
    proof = chain(private, monkeypatch, s2_bytes)
    with private.database.sessions() as db:
        row = snapshot(db, db.get(RawCapture, proof.capture_id), provenance=proof.expected)
        db.commit()
        bundle_root = private.root / 'b' / 'sha256' / proof.manifest['bundle_id']
        path = bundle_root / 'package/tire_api' / MAPPING_FILE
        if damage == 'missing-bundle':
            path.unlink()
        else:
            old = path.read_bytes()
            path.write_bytes(old.replace(b'@1', b'@9'))
        rejected(lambda: raw.checked_vehicle_parse_provenance(db, row))
        rejected(lambda: raw.checked_vehicle_bytes(db, row))


def test_same_raw_sha_new_mapping_preserves_each_original_bundle_and_ignores_current_deployment(private, monkeypatch, s2_bytes):
    first = chain(private, monkeypatch, s2_bytes)
    second = chain(private, monkeypatch, s2_bytes, mapping='xiaomi-su7-first-generation-pdf@2', revision=2)
    with private.database.sessions() as db:
        old = snapshot(db, db.get(RawCapture, first.capture_id), provenance=first.expected)
        new = snapshot(db, db.get(RawCapture, second.capture_id), provenance=second.expected)
        db.commit()
        before = deepcopy((old.payload, new.payload))
        assert old.raw_hash == new.raw_hash == S2_SHA
        assert first.expected['bundle_id'] != second.expected['bundle_id']

        def forbidden(*args, **kwargs):
            raise AssertionError('historical reader must not consult current parser or deployment')

        from tire_api import parser_releases
        monkeypatch.setattr(runtime, 'current_parser', forbidden)
        monkeypatch.setattr(runtime, 'descriptor_for_manifest', forbidden)
        monkeypatch.setattr(parser_releases, 'current_deployment', forbidden)
        assert raw.checked_vehicle_parse_provenance(db, old) == first.expected
        assert raw.checked_vehicle_parse_provenance(db, new) == second.expected
        assert raw.vehicle_raw_metadata(db, old)['mapping_id'] == MAPPING
        assert raw.vehicle_raw_metadata(db, new)['mapping_id'] == 'xiaomi-su7-first-generation-pdf@2'
        assert (old.payload, new.payload) == before

