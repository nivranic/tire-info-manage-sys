"""Real executable A/B archives; all code mutations are in temporary trusted installs."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import shutil

import pytest

from tire_api import parser_bundles as bundles, parser_runtime as runtime

BODY = (Path(__file__).parent / 'fixtures/brand_sources/hankook-runflat-pair-excerpt.html').read_text(encoding='utf-8')
QUERY = {'model': 'Ventus S1 evo3', 'size': '205/45R17'}
EAGER_ADAPTER_INIT = '''"""Versioned, deterministic adapters. No arbitrary user-supplied URLs."""

from . import registry

__all__ = ["registry"]

'''


def trusted_copy(tmp_path, monkeypatch):
    source = tmp_path / 'trusted-install' / 'tire_api'
    for path in Path(runtime.__file__).parent.rglob('*.py'):
        target = source / path.relative_to(Path(runtime.__file__).parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    monkeypatch.setattr(bundles, '_ROOT', source)
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'sealed'))
    return source


def historical_install(source, count):
    """Reconstruct the reviewed pre-Pirelli/pre-recall source, not just metadata.

    Restore the old eager adapters/__init__.py, even when the current package
    uses lazy imports. Its registry must not indirectly import an adapter that
    did not exist in the archived installation.
    Every edit is confined to the test's temporary trusted copy before sealing.
    """
    assert count in (8, 9)
    (source / 'adapters/__init__.py').write_text(EAGER_ADAPTER_INIT, encoding='utf-8')
    (source / 'adapters/pirelli.py').unlink()
    path = source / 'adapters/registry.py'
    value = path.read_text(encoding='utf-8')
    value = value.replace('from . import hankook, toyo, pirelli', 'from . import hankook, toyo')
    value = value.replace('for brand_adapter in (toyo, hankook, pirelli):', 'for brand_adapter in (toyo, hankook):')
    value = value.replace('    requires_size: bool = False\n', '')
    value = value.replace('                "requires_size": self.requires_size,\n', '')
    value = value.replace('''    selected = next(((name, url) for name, url in spec.model_urls.items() if model_key(name) == model), None)
    if selected is None:
        raise SourceAccessError("unsupported_model")
    if source_id == pirelli.SOURCE_CONFIG['id']:
        try:
            return pirelli.build_query_url({**query, 'model': selected[0]})
        except ValueError as exc:
            code = str(exc)
            raise SourceAccessError(code if code in {'source_size_required', 'unsupported_model', 'invalid_size'}
                                    else 'invalid_size') from None
    return selected[1]
''', '''    url = next((url for name, url in spec.model_urls.items() if model_key(name) == model), None)
    if url is None:
        raise SourceAccessError("unsupported_model")
    return url
''')
    value = value.replace('''    if source_id == pirelli.SOURCE_CONFIG['id']:
        return pirelli.permitted_path(url)
''', '')
    value = value.replace('''    query_target = None
    if source_id == pirelli.SOURCE_CONFIG['id']:
        try:
            query_target = query_url(query, source_id)
        except SourceAccessError as exc:
            return {'status': 'unavailable', 'reason': str(exc), **parser_metadata}
''', '')
    value = value.replace('url = query_target if query_target is not None else query_url(query, source_id)',
                          'url = query_url(query, source_id)')
    value = value.replace('"unsupported_model", "source_size_required", "invalid_size", "robots_disallowed"',
                          '"unsupported_model", "robots_disallowed"')
    if count == 8:
        value = value.replace('    from .nhtsa import source_metadata\n', '')
        value = value.replace('    values.append(source_metadata())\n', '')
    assert 'pirelli' not in value
    path.write_text(value, encoding='utf-8')
    path = source / 'parser_runtime.py'
    value = path.read_text(encoding='utf-8')
    value = value.replace('from .adapters import hankook, toyo, xiaomi, nhtsa, pirelli',
                          'from .adapters import hankook, toyo, xiaomi, nhtsa')
    value = value.replace('for adapter in (hankook, toyo, pirelli):', 'for adapter in (hankook, toyo):')
    if count == 8:
        (source / 'adapters/nhtsa.py').unlink()
        value = value.replace('from .adapters import hankook, toyo, xiaomi, nhtsa',
                              'from .adapters import hankook, toyo, xiaomi')
        value = value.replace("    values[nhtsa.SOURCE_ID] = (nhtsa.PARSER_VERSION, 'recall', ['adapters/nhtsa.py', 'adapters/transport.py', 'adapters/robots.py', 'captures.py'])\n", '')
    assert 'pirelli' not in value and (count == 9 or 'nhtsa' not in value)
    path.write_text(value, encoding='utf-8')
    path = source / 'parser_child.py'
    value = path.read_text(encoding='utf-8')
    value = value.replace('''        elif source_id == 'pirelli-us':
            from tire_api.adapters.pirelli import parse_html
            _check_imports(package_root)
            payload = parse_html(body, query)
''', '')
    if count == 8:
        value = value.replace('''        elif source_id == 'nhtsa-us-recalls':
            from tire_api.adapters.nhtsa import parse_json
            _check_imports(package_root)
            payload = parse_json(body, query)
''', '')
    assert 'pirelli' not in value and (count == 9 or 'nhtsa' not in value)
    path.write_text(value, encoding='utf-8')
    path = source / 'parser_bundles.py'
    value = path.read_text(encoding='utf-8')
    value = value.replace("_NHTSA_SOURCES = {**_LEGACY_SOURCES, 'nhtsa-us-recalls': 'recall'}\n_SOURCES = {**_NHTSA_SOURCES, 'pirelli-us': 'tire'}",
                          "_SOURCES = {**_LEGACY_SOURCES, 'nhtsa-us-recalls': 'recall'}" if count == 9 else '_SOURCES = _LEGACY_SOURCES.copy()')
    value = value.replace('(set(_LEGACY_SOURCES), set(_NHTSA_SOURCES), set(_SOURCES))',
                          '(set(_LEGACY_SOURCES), set(_SOURCES))')
    value = value.replace("        if 'pirelli-us' in parsers:\n            required.add('adapters/pirelli.py')\n", '')
    if count == 8:
        value = value.replace("        if 'nhtsa-us-recalls' in parsers:\n            required.add('adapters/nhtsa.py')\n", '')
    assert 'pirelli' not in value and (count == 9 or 'nhtsa' not in value)
    path.write_text(value, encoding='utf-8')


def mark_parser(source, value, adapter='hankook'):
    """Synthetic output marker identifies which temporary sealed code executed."""
    assert adapter in {'hankook', 'pirelli'}
    path = source / f'adapters/{adapter}.py'
    with path.open('a', encoding='utf-8') as stream:
        stream.write(f'\n_saved_parse_{value} = parse_html\ndef parse_html(body, query):\n'
                     f'    rows = _saved_parse_{value}(body, query)\n'
                     f'    for row in rows: row["facts"]["utqg_treadwear"] = {value}\n'
                     '    return rows\n')


async def execute_bundle(manifest, revision=1):
    descriptor = bundles.bundle_descriptor(manifest, 'hankook-us')
    return await runtime.parse_isolated('hankook-us', BODY, QUERY,
        descriptor['parser_version'], descriptor['parser_digest'], bundle_manifest=manifest,
        deployment_revision=revision)


def test_real_distinct_code_a_b_a_and_installed_package_precedence(tmp_path, monkeypatch):
    source = trusted_copy(tmp_path, monkeypatch)
    mark_parser(source, 111)
    first = bundles.seal_deployed_bundle()
    assert bundles.seal_deployed_bundle() == first
    mark_parser(source, 222)
    second = bundles.seal_deployed_bundle()
    assert first['bundle_id'] != second['bundle_id']
    assert first['parsers'] == second['parsers']  # identical version labels, different actual code
    original_command = runtime._command
    # A regular installed current package exists in an earlier dependency root.
    # The historical execution copy must precede it and really produce A's output.
    monkeypatch.setattr(runtime, '_command', lambda: [*original_command(), str(source.parent)])
    values = [asyncio.run(execute_bundle(manifest, revision))
              for manifest, revision in ((first, 1), (second, 2), (first, 3))]
    assert [[row['facts']['utqg_treadwear'] for row in item['payload']] for item in values] == [[111, 111], [222, 222], [111, 111]]
    for item, manifest, revision in zip(values, (first, second, first), (1, 2, 3)):
        receipt = item['receipt']
        assert receipt['bundle_id'] == manifest['bundle_id'] and receipt['deployment_revision'] == revision
        assert receipt['reaped'] and receipt['exit_code'] == 0 and len(receipt['input_hash']) == 64
    assert values[0]['receipt']['parser_digest'] == values[2]['receipt']['parser_digest']
    assert values[0]['receipt']['input_hash'] != values[2]['receipt']['input_hash']


def test_concurrent_pins_do_not_share_mutable_runtime_root(tmp_path, monkeypatch):
    source = trusted_copy(tmp_path, monkeypatch)
    mark_parser(source, 111)
    first = bundles.seal_deployed_bundle()
    mark_parser(source, 222)
    second = bundles.seal_deployed_bundle()
    async def run():
        return await asyncio.gather(execute_bundle(first), execute_bundle(second))
    results = asyncio.run(run())
    assert [value['payload'][0]['facts']['utqg_treadwear'] for value in results] == [111, 222]
    assert len({value['receipt']['pid'] for value in results}) == 2


@pytest.mark.parametrize('tamper', ['code', 'manifest', 'extra', 'missing', 'hardlink', 'pyc'])
def test_archives_fail_closed_without_current_code_fallback(tmp_path, monkeypatch, tamper):
    trusted_copy(tmp_path, monkeypatch)
    manifest = bundles.seal_deployed_bundle()
    package = bundles.verify_bundle(manifest)['package_root']
    target = package / 'adapters/hankook.py'
    if tamper == 'code':
        target.write_text('raise AssertionError("must not execute tampered code")', encoding='utf-8')
    elif tamper == 'manifest':
        (package.parent.parent / 'manifest.json').write_bytes(b'{}')
    elif tamper == 'extra':
        (package / 'unexpected.py').write_bytes(b'x = 1\n')
    elif tamper == 'missing':
        target.unlink()
    elif tamper == 'hardlink':
        os.link(target, tmp_path / 'alias.py')
    elif tamper == 'pyc':
        (package / '__pycache__').mkdir()
        (package / '__pycache__/unsafe.pyc').write_bytes(b'not executable')
    with pytest.raises(runtime.ParserRunError) as raised:
        asyncio.run(execute_bundle(manifest))
    assert raised.value.code in bundles.ERROR_CODES
    assert not raised.value.receipt.get('pid')


@pytest.mark.parametrize('field,value', [('protocol', 'future@999'), ('environment', {}), ('bundle_id', '0' * 64)])
def test_manifest_compatibility_and_content_identity(tmp_path, monkeypatch, field, value):
    trusted_copy(tmp_path, monkeypatch)
    original = bundles.seal_deployed_bundle()
    changed = deepcopy(original)
    changed[field] = value
    if field != 'bundle_id':
        changed['bundle_id'] = bundles.digest({key: item for key, item in changed.items() if key != 'bundle_id'})
    with pytest.raises(bundles.BundleError):
        bundles.bundle_descriptor(changed, 'hankook-us')


@pytest.mark.parametrize('path', ['../escape.py', 'C:/escape.py', 'a.py:secret', 'adapters\\hankook.py', 'a/../b.py'])
def test_manifest_rejects_noncanonical_paths(path):
    with pytest.raises(bundles.BundleError):
        bundles._checked_relative(path)


@pytest.mark.parametrize('catalog', [bundles._LEGACY_SOURCES, bundles._NHTSA_SOURCES, bundles._SOURCES],
                         ids=['legacy-eight', 'nhtsa-nine', 'current-ten'])
def test_only_reviewed_complete_catalogs_are_accepted(tmp_path, monkeypatch, catalog):
    trusted_copy(tmp_path, monkeypatch)
    manifest = bundles.seal_deployed_bundle()
    manifest['parsers'] = {key: value for key, value in manifest['parsers'].items() if key in catalog}
    if 'pirelli-us' not in catalog:
        del manifest['files']['adapters/pirelli.py']
    if 'nhtsa-us-recalls' not in catalog:
        del manifest['files']['adapters/nhtsa.py']
    manifest['bundle_id'] = bundles.digest({key: value for key, value in manifest.items() if key != 'bundle_id'})
    assert set(bundles.checked_manifest(manifest, protocol=runtime.PROTOCOL, limits=runtime.limits())['parsers']) == set(catalog)
    for mutation in ('subset', 'unknown', 'missing_required_file'):
        changed = deepcopy(manifest)
        if mutation == 'subset':
            del changed['parsers']['hankook-us']
        elif mutation == 'unknown':
            changed['parsers']['unreviewed-us'] = changed['parsers'].pop('hankook-us')
        else:
            required = ('adapters/pirelli.py' if 'pirelli-us' in catalog else
                        'adapters/nhtsa.py' if 'nhtsa-us-recalls' in catalog else 'adapters/hankook.py')
            del changed['files'][required]
        changed['bundle_id'] = bundles.digest({key: value for key, value in changed.items() if key != 'bundle_id'})
        with pytest.raises(bundles.BundleError) as raised:
            bundles.checked_manifest(changed, protocol=runtime.PROTOCOL, limits=runtime.limits())
        assert raised.value.code == 'parser_bundle_manifest_invalid'


def test_reconstructed_eight_source_eager_bundle_runs_tire_and_rejects_new_sources(tmp_path, monkeypatch):
    """Rebuilt reviewed legacy layout, not an original historical archive."""
    source = trusted_copy(tmp_path, monkeypatch)
    historical_install(source, 8)
    mark_parser(source, 111)
    current_catalog = runtime.source_catalog()
    old_catalog = {key: value for key, value in current_catalog.items() if key in bundles._LEGACY_SOURCES}
    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, 'source_catalog', lambda: old_catalog)
        old = bundles.seal_deployed_bundle()
    original = deepcopy(old)
    descriptor = bundles.bundle_descriptor(old, 'hankook-us')
    old_package = bundles.verify_bundle(old)['package_root']
    assert set(old['parsers']) == set(bundles._LEGACY_SOURCES)
    assert (old_package / 'adapters/__init__.py').read_text(encoding='utf-8') == EAGER_ADAPTER_INIT
    for name in ('nhtsa', 'pirelli'):
        assert f'adapters/{name}.py' not in old['files']
        assert not (old_package / f'adapters/{name}.py').exists()

    source = trusted_copy(tmp_path, monkeypatch)
    mark_parser(source, 222)
    current = bundles.seal_deployed_bundle()
    assert set(current['parsers']) == set(bundles._SOURCES)
    original_command = runtime._command
    monkeypatch.setattr(runtime, '_command', lambda: [*original_command(), str(source.parent)])
    replay = asyncio.run(execute_bundle(old))
    assert [row['facts']['utqg_treadwear'] for row in replay['payload']] == [111, 111]
    receipt = replay['receipt']
    assert receipt['pid'] and receipt['exit_code'] == 0 and receipt['reaped']
    assert receipt['bundle_id'] == old['bundle_id'] and receipt['deployment_revision'] == 1
    assert receipt['parser_digest'] == descriptor['parser_digest']
    assert receipt['execution_digest'] == descriptor['execution_digest']
    for source_id, query in (
        ('nhtsa-us-recalls', {'campaign_number': '23T001000'}),
        ('pirelli-us', {'model': 'P ZERO (PZ4)', 'size': '265/40R20'}),
    ):
        with pytest.raises(runtime.ParserRunError) as raised:
            asyncio.run(runtime.parse_isolated(source_id, b'x', query, 'synthetic@1', 'a' * 64,
                bundle_manifest=old, deployment_revision=1))
        assert raised.value.code == 'parser_source_not_allowed' and not raised.value.receipt.get('pid')
    assert old == original
    assert bundles.bundle_descriptor(old, 'hankook-us')['parser_digest'] == descriptor['parser_digest']
    assert bundles.verify_bundle(old)['manifest'] == original


def test_real_nine_source_archive_runs_saved_tire_and_recall_and_rejects_pirelli(tmp_path, monkeypatch):
    """Executable reconstructed nine-source/eager fixture, not a retained original."""
    source = trusted_copy(tmp_path, monkeypatch)
    historical_install(source, 9)
    mark_parser(source, 111)
    current_catalog = runtime.source_catalog()
    old_catalog = {key: value for key, value in current_catalog.items() if key in bundles._NHTSA_SOURCES}
    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, 'source_catalog', lambda: old_catalog)
        old = bundles.seal_deployed_bundle()
    original = deepcopy(old)
    descriptor = bundles.bundle_descriptor(old, 'hankook-us')
    # An installed current package with different tire code must not affect old imports.
    source = trusted_copy(tmp_path, monkeypatch)
    mark_parser(source, 222)
    new = bundles.seal_deployed_bundle()
    old_package = bundles.verify_bundle(old)['package_root']
    assert set(old['parsers']) == set(bundles._NHTSA_SOURCES)
    assert set(new['parsers']) == set(bundles._SOURCES)
    assert (old_package / 'adapters/__init__.py').read_text(encoding='utf-8') == EAGER_ADAPTER_INIT
    assert 'adapters/pirelli.py' not in old['files'] and not (old_package / 'adapters/pirelli.py').exists()
    assert 'pirelli' not in (old_package / 'adapters/registry.py').read_text(encoding='utf-8')
    assert 'pirelli' not in (old_package / 'parser_runtime.py').read_text(encoding='utf-8')
    original_command = runtime._command
    monkeypatch.setattr(runtime, '_command', lambda: [*original_command(), str(source.parent)])
    replay = asyncio.run(execute_bundle(old))
    assert [row['facts']['utqg_treadwear'] for row in replay['payload']] == [111, 111]
    recall = bundles.bundle_descriptor(old, 'nhtsa-us-recalls')
    raw = (Path(__file__).parent / 'fixtures/recalls/campaign-23t001000.json').read_text(encoding='utf-8')
    result = asyncio.run(runtime.parse_isolated('nhtsa-us-recalls', raw, {'campaign_number': '23T001000'},
        recall['parser_version'], recall['parser_digest'], bundle_manifest=old, deployment_revision=1))
    assert result['payload'][0]['report_received_date'] == '2023-03-02'
    for value in (replay, result):
        assert value['receipt']['pid'] and value['receipt']['reaped'] and value['receipt']['exit_code'] == 0
    with pytest.raises(runtime.ParserRunError) as raised:
        asyncio.run(runtime.parse_isolated('pirelli-us', b'x', {'model': 'P ZERO (PZ4)', 'size': '265/40R20'},
            'pirelli@1', 'a' * 64, bundle_manifest=old, deployment_revision=1))
    assert raised.value.code == 'parser_source_not_allowed' and not raised.value.receipt.get('pid')
    assert old == original
    assert bundles.bundle_descriptor(old, 'hankook-us')['parser_digest'] == descriptor['parser_digest']
    assert bundles.verify_bundle(old)['manifest'] == original


def test_reconstructed_eager_ten_bundle_keeps_own_code_with_current_lazy_install(tmp_path, monkeypatch):
    """Seal a reconstructed eager ten-source package before exposing new lazy code."""
    source = trusted_copy(tmp_path, monkeypatch)
    (source / 'adapters/__init__.py').write_text(EAGER_ADAPTER_INIT, encoding='utf-8')
    mark_parser(source, 111, adapter='pirelli')
    old = bundles.seal_deployed_bundle()
    original = deepcopy(old)
    old_descriptor = bundles.bundle_descriptor(old, 'pirelli-us')
    old_package = bundles.verify_bundle(old)['package_root']
    assert set(old['parsers']) == set(bundles._SOURCES)
    assert (old_package / 'adapters/__init__.py').read_text(encoding='utf-8') == EAGER_ADAPTER_INIT

    source = trusted_copy(tmp_path, monkeypatch)
    assert (source / 'adapters/__init__.py').read_text(encoding='utf-8') != EAGER_ADAPTER_INIT
    mark_parser(source, 222, adapter='pirelli')
    current = bundles.seal_deployed_bundle()
    current_descriptor = bundles.bundle_descriptor(current, 'pirelli-us')
    assert old['parsers'] == current['parsers'] and old['bundle_id'] != current['bundle_id']
    original_command = runtime._command
    monkeypatch.setattr(runtime, '_command', lambda: [*original_command(), str(source.parent)])
    raw = (Path(__file__).parent / 'fixtures/brand_sources/pirelli-pz4-265-40-r20-excerpt.html').read_text(encoding='utf-8')
    query = {'model': 'P ZERO (PZ4)', 'size': '265/40R20'}
    for manifest, descriptor, marker, revision in (
        (old, old_descriptor, 111, 1), (current, current_descriptor, 222, 2),
    ):
        replay = asyncio.run(runtime.parse_isolated('pirelli-us', raw, query, descriptor['parser_version'],
            descriptor['parser_digest'], bundle_manifest=manifest, deployment_revision=revision))
        assert [row['facts']['utqg_treadwear'] for row in replay['payload']] == [marker] * 3
        receipt = replay['receipt']
        assert receipt['pid'] and receipt['exit_code'] == 0 and receipt['reaped']
        assert receipt['bundle_id'] == manifest['bundle_id'] and receipt['deployment_revision'] == revision
        assert receipt['parser_digest'] == descriptor['parser_digest']
        assert receipt['execution_digest'] == descriptor['execution_digest']
    assert old == original
    assert bundles.bundle_descriptor(old, 'pirelli-us')['parser_digest'] == old_descriptor['parser_digest']
    assert bundles.verify_bundle(old)['manifest'] == original
    assert (old_package / 'adapters/__init__.py').read_text(encoding='utf-8') == EAGER_ADAPTER_INIT


def test_host_code_change_keeps_sealed_parser_identity_and_changes_execution_identity(tmp_path, monkeypatch):
    trusted_copy(tmp_path, monkeypatch)
    manifest = bundles.seal_deployed_bundle()
    descriptor = bundles.bundle_descriptor(manifest, 'hankook-us')
    host_root = tmp_path / 'updated-host'
    host_root.mkdir()
    for name in ('parser_runtime.py', 'parser_limits.py', 'parser_bundles.py'):
        (host_root / name).write_bytes((runtime._HOST_ROOT / name).read_bytes() + b'\n# trusted host update\n')
    monkeypatch.setattr(runtime, '_HOST_ROOT', host_root)
    updated = bundles.bundle_descriptor(manifest, 'hankook-us')
    assert updated['bundle_id'] == descriptor['bundle_id'] and updated['parser_digest'] == descriptor['parser_digest']
    assert updated['execution_digest'] != descriptor['execution_digest']


def test_current_ten_source_archive_executes_pirelli_with_exact_receipt(tmp_path, monkeypatch):
    from tire_api.adapters import pirelli
    trusted_copy(tmp_path, monkeypatch)
    manifest = bundles.seal_deployed_bundle()
    original = deepcopy(manifest)
    descriptor = bundles.bundle_descriptor(manifest, 'pirelli-us')
    query = {'model': 'P ZERO (PZ4)', 'size': '265/40R20'}
    raw = (Path(__file__).parent / 'fixtures/brand_sources/pirelli-pz4-265-40-r20-excerpt.html').read_text(encoding='utf-8')
    result = asyncio.run(runtime.parse_isolated('pirelli-us', raw, query, descriptor['parser_version'],
        descriptor['parser_digest'], bundle_manifest=manifest, deployment_revision=1))
    assert len(result['payload']) == 3 and result['payload'] == pirelli.parse_html(raw, query)
    receipt = result['receipt']
    assert receipt['source_id'] == 'pirelli-us' and receipt['bundle_id'] == manifest['bundle_id']
    assert receipt['deployment_revision'] == 1 and receipt['parser_digest'] == descriptor['parser_digest']
    assert receipt['execution_digest'] == descriptor['execution_digest']
    assert receipt['pid'] and receipt['exit_code'] == 0 and receipt['reaped']
    assert bundles.verify_bundle(manifest)['manifest'] == original
