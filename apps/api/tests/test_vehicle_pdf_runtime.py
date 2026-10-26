"""Real PDF child integration with reviewed S2 bytes and private sealed bundles.

The old-version fixture is a reconstructed nine-source package with byte-exact
1.0.1 Xiaomi source, not a retained historical bundle. No network fetch or normal database is started; shared fixture imports stay inside the managed test boundary.
"""
import asyncio
from copy import deepcopy
import hashlib
import os
from pathlib import Path

import pytest

from tire_api import parser_bundles as bundles, parser_runtime as runtime
from tire_api.adapters import xiaomi
from tire_api.adapters.xiaomi_first_generation_pdf import parse_reviewed_pdf
from test_parser_bundles import historical_install, trusted_copy
from test_vehicles import body as current_json

SOURCE = 'xiaomi-cn-vehicles'
VEHICLE = 'xiaomi-su7-first-generation'
NEW_VERSION = 'xiaomi-param-comparison@1.1.0'
OLD_VERSION = 'xiaomi-param-comparison@1.0.1'
OLD_XIAOMI_SHA = 'ca9bc74fca9b28c832306bdba9a0b2fe4532623f292572ee5918e29e13b8d997'
MAPPING_FILE = 'adapters/xiaomi_first_generation_pdf.py'
S2_SHA = '0ab998099f84760224071ba9fbefee9c61650d44b994fc82979bed76e086c60f'
S2_SIZE = 3240150
S2_PATH = (Path(__file__).resolve().parents[3] / '.artifacts'
    / 'r81-source-and-regression-1e21a0bd37e447c39c7b934ead5a299f' / 'xiaomi-first-generation-2.pdf')


@pytest.fixture
def installation(tmp_path, monkeypatch):
    return trusted_copy(tmp_path, monkeypatch)


@pytest.fixture
def reviewed_pdf():
    # Each invocation is a pre-use observation, outside the source binding list.
    def load():
        assert S2_PATH.is_file(), 'reviewed historical S2 PDF is required for this integration gate'
        raw = S2_PATH.read_bytes()
        assert len(raw) == S2_SIZE and hashlib.sha256(raw).hexdigest() == S2_SHA
        with pytest.raises(UnicodeDecodeError):
            raw.decode('utf-8', errors='strict')
        return raw
    return load


def execute(manifest, raw, vehicle=VEHICLE, *, source=SOURCE, query=None):
    descriptor = bundles.bundle_descriptor(manifest, source)
    query = {'vehicle_id': vehicle} if query is None else query
    return asyncio.run(runtime.parse_isolated(source, raw, query,
        descriptor['parser_version'], descriptor['parser_digest'],
        bundle_manifest=manifest, deployment_revision=7))


def assert_receipt(value, manifest, raw, vehicle=VEHICLE):
    receipt = value['receipt']
    descriptor = bundles.bundle_descriptor(manifest, SOURCE)
    assert receipt['pid'] and receipt['pid'] != os.getpid()
    assert receipt['exit_code'] == 0 and receipt['reaped']
    assert receipt['bundle_id'] == manifest['bundle_id']
    assert receipt['parser_version'] == descriptor['parser_version']
    assert receipt['parser_digest'] == descriptor['parser_digest']
    assert receipt['execution_digest'] == descriptor['execution_digest']
    assert receipt['deployment_revision'] == 7
    assert receipt['input_hash'] == runtime.input_hash(
        {**receipt, 'query': {'vehicle_id': vehicle}}, raw if isinstance(raw, bytes) else raw.encode('utf-8'))
    assert receipt['limits'] == runtime.limits()
    assert receipt['stderr_bytes'] == 0 and receipt['stdout_bytes'] <= runtime.MAX_OUTPUT_BYTES
    assert receipt['limits_backend'] == ('windows_job_object' if os.name == 'nt' else 'linux_resource_process_group')


def assert_child_failure(call, code):
    with pytest.raises(runtime.ParserRunError) as raised:
        call()
    assert raised.value.code == code
    receipt = raised.value.receipt
    assert receipt['pid'] and receipt['reaped'] and receipt['exit_code'] == 0
    assert receipt['stderr_bytes'] == 0
    return receipt


def restore_old_xiaomi(source):
    path = source / 'adapters/xiaomi.py'
    raw = path.read_bytes()
    before = b'PARSER_VERSION = "xiaomi-param-comparison@1.1.0"'
    after = b'PARSER_VERSION = "xiaomi-param-comparison@1.0.1"'
    assert raw.count(before) == 1
    restored = raw.replace(before, after, 1)
    assert hashlib.sha256(restored).hexdigest() == OLD_XIAOMI_SHA
    path.write_bytes(restored)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == OLD_XIAOMI_SHA


def seal_reconstructed_old_nine(source, monkeypatch, *, mapping=True):
    restore_old_xiaomi(source)
    historical_install(source, 9)
    if not mapping:
        (source / MAPPING_FILE).unlink()
    catalog = {key: deepcopy(value) for key, value in runtime.source_catalog().items()
               if key in bundles._NHTSA_SOURCES}
    catalog[SOURCE]['parser_version'] = OLD_VERSION
    monkeypatch.setattr(runtime, 'source_catalog', lambda: catalog)
    manifest = bundles.seal_deployed_bundle()
    assert set(manifest['parsers']) == set(bundles._NHTSA_SOURCES)
    assert manifest['files']['adapters/xiaomi.py']['sha256'] == OLD_XIAOMI_SHA
    assert (MAPPING_FILE in manifest['files']) is mapping
    return manifest


def test_new_shared_version_keeps_current_json_contract(installation):
    manifest = bundles.seal_deployed_bundle()
    assert manifest['parsers'][SOURCE]['parser_version'] == NEW_VERSION
    raw = current_json()
    result = execute(manifest, raw, xiaomi.CURRENT_ID)
    assert result['payload'] == xiaomi.parse_config(raw)
    assert_receipt(result, manifest, raw, xiaomi.CURRENT_ID)


def test_real_non_utf8_s2_executes_selected_sealed_pdf_mapping(installation, reviewed_pdf):
    manifest = bundles.seal_deployed_bundle()
    assert MAPPING_FILE in manifest['files']
    raw = reviewed_pdf()
    result = execute(manifest, raw)
    assert result['payload'] == parse_reviewed_pdf(raw, VEHICLE)
    assert len(result['payload']['trims']) == 3 and len(result['payload']['fitments']) == 15
    assert result['payload']['parse_method'] == 'sha256_bound_reviewed_mapping'
    assert result['payload']['mapping_id'] == 'xiaomi-su7-first-generation-pdf@1'
    assert 'parse_provenance' not in result['payload']
    assert_receipt(result, manifest, raw)


@pytest.mark.parametrize('mapping', [True, False], ids=['mapping-present', 'mapping-absent'])
def test_reconstructed_old_nine_keeps_json_and_rejects_pdf(installation, monkeypatch, reviewed_pdf, mapping):
    manifest = seal_reconstructed_old_nine(installation, monkeypatch, mapping=mapping)
    raw = current_json()
    result = execute(manifest, raw, xiaomi.CURRENT_ID)
    assert result['payload'] == xiaomi.parse_config(raw)
    assert_receipt(result, manifest, raw, xiaomi.CURRENT_ID)
    raw = reviewed_pdf()
    assert_child_failure(lambda: execute(manifest, raw), 'parser_schema_changed')
    assert bundles.verify_bundle(manifest)['manifest'] == manifest


def test_new_pdf_capability_requires_mapping_in_manifest(installation):
    (installation / MAPPING_FILE).unlink()
    with pytest.raises(bundles.BundleError, match='^parser_bundle_manifest_invalid$'):
        bundles.seal_deployed_bundle()


@pytest.mark.parametrize('case', ['signature', 'unknown-revision', 'same-size-unknown'],
    ids=['signature', 'unknown-revision', 'same-size-unknown'])
def test_pdf_errors_cross_only_as_fixed_safe_codes(installation, case):
    manifest = bundles.seal_deployed_bundle()
    if case == 'signature':
        raw, expected = b'not a PDF', 'vehicle_pdf_invalid'
    elif case == 'unknown-revision':
        raw, expected = b'%PDF-1.7\nsynthetic unknown\x80', 'vehicle_pdf_revision_unreviewed'
    else:
        raw, expected = b'%PDF-' + b'x' * (S2_SIZE - 5), 'vehicle_pdf_revision_unreviewed'
    assert_child_failure(lambda: execute(manifest, raw), expected)


def test_unlisted_mapping_error_is_not_exposed(installation):
    path = installation / MAPPING_FILE
    raw = path.read_bytes()
    old = b'raise ReviewedPDFError("vehicle_pdf_revision_unreviewed")'
    assert raw.count(old) == 1
    path.write_bytes(raw.replace(old, b'raise ReviewedPDFError("unlisted_synthetic_private_diagnostic")', 1))
    manifest = bundles.seal_deployed_bundle()
    assert_child_failure(lambda: execute(manifest, b'%PDF-1.7\nunknown'), 'parser_schema_changed')


def test_declared_pdf_version_must_match_selected_sealed_xiaomi_module(installation):
    restore_old_xiaomi(installation)
    # The trusted fixture deliberately declares 1.1.0 over exact 1.0.1 code.
    manifest = bundles.seal_deployed_bundle()
    assert manifest['parsers'][SOURCE]['parser_version'] == NEW_VERSION
    assert manifest['files']['adapters/xiaomi.py']['sha256'] == OLD_XIAOMI_SHA
    assert_child_failure(lambda: execute(manifest, b'%PDF-1.7\nunknown'), 'parser_schema_changed')


@pytest.mark.parametrize('version', ['xiaomi-param-comparison@1.1.1', 'xiaomi-param-comparison@2.0.0'],
    ids=['unreviewed-patch', 'unreviewed-major'])
def test_pdf_capability_is_an_exact_reviewed_version(installation, monkeypatch, version):
    path = installation / 'adapters/xiaomi.py'
    raw = path.read_bytes()
    old = b'PARSER_VERSION = "xiaomi-param-comparison@1.1.0"'
    assert raw.count(old) == 1
    path.write_bytes(raw.replace(old, ('PARSER_VERSION = "' + version + '"').encode('ascii'), 1))
    catalog = deepcopy(runtime.source_catalog())
    catalog[SOURCE]['parser_version'] = version
    monkeypatch.setattr(runtime, 'source_catalog', lambda: catalog)
    manifest = bundles.seal_deployed_bundle()
    assert_child_failure(lambda: execute(manifest, b'%PDF-1.7\nunknown'), 'parser_schema_changed')


@pytest.mark.parametrize('case', ['current-vehicle', 'other-source'], ids=['current-vehicle', 'other-source'])
def test_pdf_bytes_do_not_relax_other_text_parser_utf8(installation, case):
    manifest = bundles.seal_deployed_bundle()
    raw = b'%PDF-1.7\nsynthetic\x80'
    if case == 'current-vehicle':
        call = lambda: execute(manifest, raw, xiaomi.CURRENT_ID)
    else:
        call = lambda: execute(manifest, raw, source='michelin-us', query={})
    assert_child_failure(call, 'parser_schema_changed')



@pytest.mark.parametrize('damage', ['missing', 'changed'], ids=['missing', 'changed'])
def test_sealed_mapping_integrity_failure_never_falls_back_to_installation(installation, damage):
    manifest = bundles.seal_deployed_bundle()
    package = bundles.verify_bundle(manifest)['package_root']
    path = package / MAPPING_FILE
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b'\n# synthetic sealed-code tamper\n')
    with pytest.raises(runtime.ParserRunError) as raised:
        execute(manifest, b'%PDF-1.7\nunknown')
    assert raised.value.code == 'parser_bundle_integrity_failed'
    assert not raised.value.receipt.get('pid')


def test_sealed_mapping_is_not_replaced_by_mutable_install(installation, reviewed_pdf):
    first = bundles.seal_deployed_bundle()
    path = installation / MAPPING_FILE
    raw = path.read_bytes()
    old = b'MAPPING_ID = "xiaomi-su7-first-generation-pdf@1"'
    assert raw.count(old) == 1
    path.write_bytes(raw.replace(old, b'MAPPING_ID = "xiaomi-su7-first-generation-pdf@2"', 1))
    second = bundles.seal_deployed_bundle()
    assert first['bundle_id'] != second['bundle_id']
    for manifest, expected in ((first, 'xiaomi-su7-first-generation-pdf@1'),
                               (second, 'xiaomi-su7-first-generation-pdf@2'),
                               (first, 'xiaomi-su7-first-generation-pdf@1')):
        raw = reviewed_pdf()
        result = execute(manifest, raw)
        assert result['payload']['mapping_id'] == expected
        assert_receipt(result, manifest, raw)
