"""Source-only protected imports, with executable cache positive/negative controls.

All modules and bytecode in these tests are synthetic temporary files. These
tests exercise import policy in this interpreter, not HTTP, models or a parser
subprocess. Runtime/OS/sealed-process coverage belongs to the existing suites.
"""
import importlib
from importlib.machinery import EXTENSION_SUFFIXES, ModuleSpec, SourceFileLoader
from pathlib import Path
import os
import py_compile
import sys
import types

import pytest

from tire_api import parser_child as child

DENIED = 'parser_source_import_not_allowed'
HOST_NAMES = ('parser_runtime', 'parser_limits', 'parser_bundles', 'parser_child')
SOURCE = b"VALUE = 'source'\n"
CACHED = b"VALUE = 'cached'\n"


def protected(name):
    return name == 'tire_api' or name.startswith('tire_api.') or name == '_tire_parser_host' or name.startswith('_tire_parser_host.')


@pytest.fixture
def roots(tmp_path, monkeypatch):
    host = tmp_path / 'host'
    package = tmp_path / 'execution' / 'tire_api'
    host.mkdir()
    package.mkdir(parents=True)
    (package / '__init__.py').write_bytes(b'# synthetic execution package\n')
    for name in HOST_NAMES:
        (host / f'{name}.py').write_bytes(SOURCE)
    original_modules = {name: module for name, module in sys.modules.items() if protected(name)}
    monkeypatch.setattr(sys, 'meta_path', list(sys.meta_path))
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    monkeypatch.setattr(sys, 'pycache_prefix', None)
    for name, directory in (('_tire_parser_host', host), ('tire_api', package)):
        module = types.ModuleType(name)
        module.__path__ = [str(directory)]
        module.__spec__ = ModuleSpec(name, loader=None, is_package=True)
        module.__spec__.submodule_search_locations = module.__path__
        if name == 'tire_api':
            module.__file__ = str(directory / '__init__.py')
        sys.modules[name] = module
    # Keep the already imported implementation in the test's local `child`
    # reference; fake protected children must not resolve to old sys.modules.
    for name in tuple(original_modules):
        if name not in {'tire_api', '_tire_parser_host'}:
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    try:
        yield host, package
    finally:
        for name in tuple(sys.modules):
            if protected(name) or name == 'round32_cached_dependency':
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)
        importlib.invalidate_caches()


def timestamp_valid_stale(source, *, cfile=None):
    """A normal timestamp/size check accepts this cache despite differing code."""
    assert len(SOURCE) == len(CACHED)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(CACHED)
    timestamp = 1_700_000_000
    os.utime(source, (timestamp, timestamp))
    cached = Path(py_compile.compile(
        str(source), cfile=str(cfile) if cfile else None, doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP))
    source.write_bytes(SOURCE)
    os.utime(source, (timestamp, timestamp))
    header = cached.read_bytes()[:16]
    assert int.from_bytes(header[4:8], 'little') == 0  # timestamp cache, not hash cache
    assert int.from_bytes(header[8:12], 'little') == int(source.stat().st_mtime)
    assert int.from_bytes(header[12:16], 'little') == source.stat().st_size == len(CACHED)
    return cached


@pytest.mark.parametrize('name', HOST_NAMES)
def test_all_four_registered_host_modules_ignore_timestamp_valid_cache(roots, name):
    host, package = roots
    cache = timestamp_valid_stale(host / f'{name}.py')
    finder = child._install_source_only_finder(host, package)
    assert sys.meta_path[0] is finder and sys.pycache_prefix is None and sys.dont_write_bytecode
    module = importlib.import_module('_tire_parser_host.' + name)
    assert module.VALUE == 'source' and cache.is_file()
    assert isinstance(module.__loader__, child._SourceOnlyLoader)


def test_selected_application_module_ignores_timestamp_valid_cache(roots):
    host, package = roots
    cache = timestamp_valid_stale(package / 'cache_leaf.py')
    child._install_source_only_finder(host, package)
    module = importlib.import_module('tire_api.cache_leaf')
    assert module.VALUE == 'source' and cache.is_file()
    assert Path(module.__file__).resolve().is_relative_to(package)
    assert isinstance(module.__loader__, child._SourceOnlyLoader)


def test_late_host_import_and_reload_remain_source_only_after_cache_restore(roots):
    host, package = roots
    finder = child._install_source_only_finder(host, package)
    assert sys.pycache_prefix is None
    # parser_limits is deliberately not imported when the finder is installed.
    timestamp_valid_stale(host / 'parser_limits.py')
    module = importlib.import_module('_tire_parser_host.parser_limits')
    assert module.VALUE == 'source'
    timestamp_valid_stale(host / 'parser_limits.py')
    module.VALUE = 'changed-in-memory'
    assert importlib.reload(module).VALUE == 'source'
    assert sys.meta_path[0] is finder and sys.pycache_prefix is None


def test_unregistered_host_helper_is_denied_before_any_canary_executes(roots, tmp_path):
    host, package = roots
    canary = tmp_path / 'unexpected-helper-ran'
    (host / 'future_helper.py').write_text(
        f'from pathlib import Path\nPath({str(canary)!r}).write_text("executed")\n', encoding='utf-8')
    child._install_source_only_finder(host, package)
    with pytest.raises(ImportError, match=DENIED):
        importlib.import_module('_tire_parser_host.future_helper')
    assert not canary.exists()


def test_trusted_dependency_cache_is_used_with_different_source_value(roots, tmp_path, monkeypatch):
    host, package = roots
    dependencies = tmp_path / 'dependencies'
    source = dependencies / 'round32_cached_dependency.py'
    cache = timestamp_valid_stale(source)
    monkeypatch.syspath_prepend(str(dependencies))
    finder = child._install_source_only_finder(host, package)
    assert finder.find_spec('round32_cached_dependency') is None
    module = importlib.import_module('round32_cached_dependency')
    assert module.VALUE == 'cached'  # source contains 'source': proves actual cache use
    assert source.read_bytes() == SOURCE and cache.is_file() and sys.dont_write_bytecode


def test_removing_finder_exposes_timestamp_valid_host_cache_negative_control(roots):
    host, package = roots
    timestamp_valid_stale(host / 'parser_limits.py')
    finder = child._install_source_only_finder(host, package)
    sys.meta_path.remove(finder)
    module = importlib.import_module('_tire_parser_host.parser_limits')
    assert sys.pycache_prefix is None and sys.dont_write_bytecode
    assert module.VALUE == 'cached' and module.VALUE != 'source'


@pytest.mark.parametrize('kind', ['namespace', 'pyc_only', 'native'])
def test_selected_application_namespace_bytecode_only_and_native_are_denied(roots, kind):
    host, package = roots
    if kind == 'namespace':
        (package / 'bad_leaf').mkdir()
    elif kind == 'pyc_only':
        source = package / 'bad_leaf.py'
        timestamp_valid_stale(source, cfile=package / 'bad_leaf.pyc')
        source.unlink()
    else:
        (package / ('bad_leaf' + EXTENSION_SUFFIXES[0])).write_bytes(b'not an executable extension')
    finder = child._install_source_only_finder(host, package)
    with pytest.raises(ImportError, match=DENIED):
        finder.find_spec('tire_api.bad_leaf', [str(package)])


def test_protected_find_spec_cannot_return_source_outside_selected_tree(roots, tmp_path, monkeypatch):
    host, package = roots
    outside = tmp_path / 'outside.py'
    outside.write_bytes(SOURCE)
    name = 'tire_api.outside'
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(outside)))
    finder = child._install_source_only_finder(host, package)
    monkeypatch.setattr(child.PathFinder, 'find_spec', lambda *_: spec)
    with pytest.raises(ImportError, match=DENIED):
        finder.find_spec(name, [str(tmp_path)])


@pytest.mark.parametrize('invalid_locations', ['outside', 'multiple'])
def test_package_search_locations_cannot_escape_or_expand_selected_tree(roots, tmp_path, monkeypatch, invalid_locations):
    host, package = roots
    nested = package / 'nested'
    nested.mkdir()
    (nested / '__init__.py').write_bytes(SOURCE)
    name = 'tire_api.nested'
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(nested / '__init__.py')), is_package=True)
    spec.submodule_search_locations = [str(tmp_path)] if invalid_locations == 'outside' else [str(nested), str(tmp_path)]
    finder = child._install_source_only_finder(host, package)
    monkeypatch.setattr(child.PathFinder, 'find_spec', lambda *_: spec)
    with pytest.raises(ImportError, match=DENIED):
        finder.find_spec(name, [str(package)])


@pytest.mark.parametrize('name', ['_tire_parser_host', '_tire_parser_host.parser_limits.nested', 'tire_api.missing'])
def test_missing_or_unregistered_protected_names_do_not_fall_through(roots, name):
    finder = child._install_source_only_finder(*roots)
    with pytest.raises(ImportError, match=DENIED):
        finder.find_spec(name)


def test_unprotected_dependency_and_standard_namespace_delegate(roots):
    finder = child._install_source_only_finder(*roots)
    for name in ('json', 'importlib.resources', 'pydantic', 'round32_cached_dependency'):
        assert finder.find_spec(name) is None
