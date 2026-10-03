"""Locally sealed trusted parser source. No upload, path or code execution API.

Immutability is an application/storage contract, not an OS-user security sandbox.
Only a manifest supplied by the trusted deployment registry authorizes execution.
"""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import tempfile

SCHEMA = 'trusted-parser-bundle@1'
_ROOT = Path(__file__).absolute().parent
_LEGACY_SOURCES = {'michelin-us': 'tire', 'michelin-uk': 'tire', 'michelin-fr': 'tire',
            'michelin-de': 'tire', 'michelin-cn': 'tire', 'toyo-us': 'tire',
            'hankook-us': 'tire', 'xiaomi-cn-vehicles': 'vehicle'}
_NHTSA_SOURCES = {**_LEGACY_SOURCES, 'nhtsa-us-recalls': 'recall'}
_SOURCES = {**_NHTSA_SOURCES, 'pirelli-us': 'tire'}
_HASH = re.compile(r'^[a-f0-9]{64}$')
MAX_FILES = 256
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
ERROR_CODES = frozenset({'parser_bundle_missing', 'parser_bundle_link_forbidden', 'parser_bundle_integrity_failed',
    'parser_bundle_dependency_ambiguous', 'parser_bundle_too_large', 'parser_bundle_manifest_invalid',
    'parser_bundle_source_changed', 'parser_bundle_policy_incompatible', 'parser_bundle_environment_incompatible',
    'parser_bundle_storage_unavailable'})


class BundleError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _plain_path(path, *, directory=None):
    """Reject links/reparse points in every existing path component."""
    path = Path(path).absolute()
    for candidate in [*reversed(path.parents), path]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            raise BundleError('parser_bundle_missing') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise BundleError('parser_bundle_link_forbidden')
    info = path.stat()
    if directory is True and not stat.S_ISDIR(info.st_mode):
        raise BundleError('parser_bundle_integrity_failed')
    if directory is False and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise BundleError('parser_bundle_link_forbidden')
    return path


def _environment():
    # Conservative closure: changes to any installed distribution require an
    # explicit re-seal, including indirect imports through captures/db/adapters.
    dependencies = {}
    for item in importlib.metadata.distributions():
        name = re.sub(r'[-_.]+', '-', item.metadata['Name']).lower()
        if name in dependencies and dependencies[name] != item.version:
            raise BundleError('parser_bundle_dependency_ambiguous')
        dependencies[name] = item.version
    return {'python': list(sys.version_info[:3]), 'implementation': sys.implementation.name,
            'cache_tag': sys.implementation.cache_tag, 'platform': sys.platform,
            'machine': platform.machine().lower(), 'dependencies': dict(sorted(dependencies.items()))}


def _tree(root, *, source=False):
    root = _plain_path(root, directory=True)
    found = {}
    total = 0

    def walk(directory):
        nonlocal total
        for path in sorted(directory.iterdir()):
            _plain_path(path)
            if path.is_dir():
                if source and path.name in {'__pycache__', 'build'}:
                    continue
                walk(path)
            else:
                if source and path.suffix != '.py':
                    continue
                _plain_path(path, directory=False)
                if path.suffix != '.py' or path.stat().st_size > MAX_FILE_BYTES:
                    raise BundleError('parser_bundle_integrity_failed')
                relative = path.relative_to(root).as_posix()
                _checked_relative(relative)
                with path.open('rb') as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise BundleError('parser_bundle_integrity_failed')
                total += len(data)
                if total > MAX_TOTAL_BYTES or len(found) >= MAX_FILES:
                    raise BundleError('parser_bundle_too_large')
                found[relative] = data
    walk(root)
    if not found:
        raise BundleError('parser_bundle_integrity_failed')
    return found


def _checked_relative(value):
    if not isinstance(value, str) or len(value) > 220 or '\\' in value:
        raise BundleError('parser_bundle_manifest_invalid')
    parts = PurePosixPath(value).parts
    if (not parts or PurePosixPath(value).is_absolute() or '/'.join(parts) != value
            or not value.endswith('.py') or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.?[A-Za-z0-9_]*', part)
                                               or part in {'.', '..', '__pycache__', 'build'}
                                               or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}
                                               for part in parts)):
        raise BundleError('parser_bundle_manifest_invalid')
    return value


def _metadata(values):
    return {name: {'sha256': hashlib.sha256(data).hexdigest(), 'byte_count': len(data)}
            for name, data in sorted(values.items())}


def snapshot_manifest(root, parsers, protocol, limits):
    """Internal trusted-source snapshot; never accepts HTTP paths."""
    first = _tree(root, source=True)
    manifest = {'schema': SCHEMA, 'files': _metadata(first), 'parsers': parsers,
                'environment': _environment(), 'protocol': protocol, 'limits': limits}
    manifest['bundle_id'] = digest(manifest)
    checked_manifest(manifest, protocol=protocol, limits=limits)
    if _metadata(_tree(root, source=True)) != manifest['files']:
        raise BundleError('parser_bundle_source_changed')
    return manifest


def checked_manifest(manifest, *, protocol, limits, environment=True):
    try:
        if not isinstance(manifest, dict) or set(manifest) != {'schema', 'bundle_id', 'files', 'parsers', 'environment', 'protocol', 'limits'}:
            raise BundleError('parser_bundle_manifest_invalid')
        manifest = json.loads(canonical(manifest))
        if manifest['schema'] != SCHEMA or not isinstance(manifest['bundle_id'], str) or not _HASH.fullmatch(manifest['bundle_id']):
            raise BundleError('parser_bundle_manifest_invalid')
        if digest({key: value for key, value in manifest.items() if key != 'bundle_id'}) != manifest['bundle_id']:
            raise BundleError('parser_bundle_integrity_failed')
        if manifest['protocol'] != protocol or manifest['limits'] != limits:
            raise BundleError('parser_bundle_policy_incompatible')
        if environment and manifest['environment'] != _environment():
            raise BundleError('parser_bundle_environment_incompatible')
        files, parsers = manifest['files'], manifest['parsers']
        # Existing sealed eight/nine-source packages remain executable. Accept only
        # reviewed complete catalogs, never arbitrary subsets or unknown sources.
        if (not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES or not isinstance(parsers, dict)
                or set(parsers) not in (set(_LEGACY_SOURCES), set(_NHTSA_SOURCES), set(_SOURCES))):
            raise BundleError('parser_bundle_manifest_invalid')
        total, folded = 0, set()
        for name, item in files.items():
            _checked_relative(name)
            if name.casefold() in folded:
                raise BundleError('parser_bundle_manifest_invalid')
            folded.add(name.casefold())
            if (not isinstance(item, dict) or set(item) != {'sha256', 'byte_count'}
                    or not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256'])
                    or type(item['byte_count']) is not int or not 0 <= item['byte_count'] <= MAX_FILE_BYTES):
                raise BundleError('parser_bundle_manifest_invalid')
            total += item['byte_count']
        required = {'__init__.py', 'domain.py', 'parser_runtime.py', 'parser_child.py', 'parser_limits.py',
                    'adapters/__init__.py', 'adapters/michelin.py', 'adapters/michelin_regions.py',
                    'adapters/toyo.py', 'adapters/hankook.py', 'adapters/xiaomi.py'}
        if 'nhtsa-us-recalls' in parsers:
            required.add('adapters/nhtsa.py')
        if 'pirelli-us' in parsers:
            required.add('adapters/pirelli.py')
        if not required <= set(files) or total > MAX_TOTAL_BYTES:
            raise BundleError('parser_bundle_manifest_invalid')
        for source, item in parsers.items():
            if (not isinstance(item, dict) or set(item) != {'parser_version', 'target_kind'}
                    or item['target_kind'] != _SOURCES[source]
                    or not isinstance(item['parser_version'], str)
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._@+-]{0,99}', item['parser_version'])):
                raise BundleError('parser_bundle_manifest_invalid')
        return manifest
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise BundleError('parser_bundle_manifest_invalid') from None


def verify_tree(package_root, manifest):
    """Files must match exactly; extra caches/code cannot affect imports."""
    if _metadata(_tree(package_root)) != manifest['files']:
        raise BundleError('parser_bundle_integrity_failed')


def copy_verified(package_root, manifest, destination, *, source=False):
    values = _tree(package_root, source=source)
    if _metadata(values) != manifest['files']:
        raise BundleError('parser_bundle_integrity_failed')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    _plain_path(destination, directory=True)
    for name, data in values.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    verify_tree(destination, manifest)
    if _metadata(_tree(package_root, source=source)) != manifest['files']:
        raise BundleError('parser_bundle_integrity_failed')


def _store_root(*, create=False):
    root = Path(os.getenv('TI_PARSER_BUNDLE_ROOT') or 'data/parser-bundles').absolute()
    # Check existing ancestors before mkdir to reject redirected writes.
    for path in [*reversed(root.parents), root]:
        if path.exists() or path.is_symlink():
            _plain_path(path, directory=True)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return _plain_path(root, directory=True)


def _policy():
    from . import parser_runtime
    return parser_runtime


def seal_deployed_bundle():
    runtime = _policy()
    try:
        manifest = snapshot_manifest(_ROOT, runtime.source_catalog(), runtime.PROTOCOL, runtime.limits())
        root = _store_root(create=True)
        published = root / 'sha256' / manifest['bundle_id']
        staging_root = root / '.staging'
        for directory in (published.parent, staging_root):
            directory.mkdir(exist_ok=True)
            _plain_path(directory, directory=True)
        if published.exists() or published.is_symlink():
            verify_bundle(manifest)
            return manifest
        staging = Path(tempfile.mkdtemp(prefix='seal-', dir=staging_root))
        try:
            copy_verified(_ROOT, manifest, staging / 'package' / 'tire_api', source=True)
            with (staging / 'manifest.json').open('xb') as stream:
                stream.write(canonical(manifest))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # A completed destination is nonempty: rename cannot overwrite
                # another successful publisher on supported Windows/Linux.
                staging.rename(published)
            except FileExistsError:
                verify_bundle(manifest)
            except OSError:
                if not published.exists():
                    raise
                verify_bundle(manifest)
            verify_bundle(manifest)
            return manifest
        finally:
            if staging.exists():
                _plain_path(staging, directory=True)
                if not staging.resolve().is_relative_to(staging_root.resolve()) or not staging.name.startswith('seal-'):
                    raise BundleError('parser_bundle_storage_unavailable')
                shutil.rmtree(staging)
    except BundleError:
        raise
    except (OSError, RuntimeError):
        raise BundleError('parser_bundle_storage_unavailable') from None


def verify_bundle(manifest):
    runtime = _policy()
    manifest = checked_manifest(manifest, protocol=runtime.PROTOCOL, limits=runtime.limits())
    try:
        root = _store_root() / 'sha256' / manifest['bundle_id']
        _plain_path(root, directory=True)
        if {path.name for path in root.iterdir()} != {'manifest.json', 'package'}:
            raise BundleError('parser_bundle_integrity_failed')
        stored = _plain_path(root / 'manifest.json', directory=False)
        with stored.open('rb') as stream:
            stored_bytes = stream.read(128 * 1024 + 1)
        if len(stored_bytes) > 128 * 1024 or stored_bytes != canonical(manifest):
            raise BundleError('parser_bundle_integrity_failed')
        package = _plain_path(root / 'package', directory=True)
        if {path.name for path in package.iterdir()} != {'tire_api'}:
            raise BundleError('parser_bundle_integrity_failed')
        package_root = package / 'tire_api'
        verify_tree(package_root, manifest)
        return {'bundle_id': manifest['bundle_id'], 'manifest': manifest, 'package_root': package_root}
    except BundleError:
        raise
    except OSError:
        raise BundleError('parser_bundle_storage_unavailable') from None


def bundle_descriptor(manifest, source_id):
    runtime = _policy()
    checked = checked_manifest(manifest, protocol=runtime.PROTOCOL, limits=runtime.limits())
    return runtime.descriptor_for_manifest(checked, source_id)
