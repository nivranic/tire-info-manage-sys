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
_DOCUMENT_SOURCES = {**_SOURCES, 'workspace-pdf-text': 'document'}
_BRIDGESTONE_SOURCES = {**_DOCUMENT_SOURCES, 'bridgestone-jp': 'tire'}
_CONTINENTAL_SOURCES = {**_BRIDGESTONE_SOURCES, 'continental-cn': 'tire'}
_GOODYEAR_SOURCES = {**_CONTINENTAL_SOURCES, 'goodyear-sg': 'tire'}
_SAFETY_GATE_SOURCES = {**_GOODYEAR_SOURCES, 'eu-safety-gate': 'recall'}
_YOKOHAMA_SOURCES = {**_SAFETY_GATE_SOURCES, 'yokohama-eu': 'tire'}
_DUNLOP_SOURCES = {**_YOKOHAMA_SOURCES, 'dunlop-eu': 'tire'}
_SAMR_SOURCES = {**_DUNLOP_SOURCES, 'samr-cn-recalls': 'recall'}
# Exact reviewed capability versions; file presence alone never enables PDF.
XIAOMI_PDF_PARSER_VERSIONS = frozenset({'xiaomi-param-comparison@1.1.0'})
XIAOMI_PDF_MAPPING_FILE = 'adapters/xiaomi_first_generation_pdf.py'
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


def _filesystem_path(path):
    """Use long-path-capable Windows spellings without resolving ancestors.

    Win32 parent, reserved-name, stream and trailing-dot/space spellings are not
    canonical filesystem paths. Preserve those and explicit namespaces as given.
    """
    path = Path(path).absolute()
    if os.name != 'nt':
        return path
    value = str(path)
    if value.startswith(('\\\\?\\', '\\\\.\\')):
        return path
    components = list(path.parts[1:])
    if path.drive.startswith('\\\\'):
        components.extend(path.drive[2:].split('\\'))
    # Python 3.13+ exposes the platform rule directly; 3.12 provides the same
    # reserved device-name check on Windows paths. No file or device is opened.
    is_reserved = getattr(os.path, 'isreserved', lambda part: Path(part).is_reserved())
    if any(part == '..' or part.endswith(('.', ' ')) or ':' in part or is_reserved(part)
           for part in components):
        return path
    if path.drive.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + value[2:])
    if len(path.drive) == 2 and path.drive[1] == ':' and path.drive[0].isascii() and path.drive[0].isalpha():
        return Path('\\\\?\\' + value)
    return path


def _plain_path_info(path, *, directory=None):
    """Validate every component once, retaining the leaf's no-follow metadata."""
    path = _filesystem_path(path)
    for candidate in [*reversed(path.parents), path]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            raise BundleError('parser_bundle_missing') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise BundleError('parser_bundle_link_forbidden')
    if directory is True and not stat.S_ISDIR(info.st_mode):
        raise BundleError('parser_bundle_integrity_failed')
    if directory is False and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise BundleError('parser_bundle_link_forbidden')
    return path, info


def _plain_path(path, *, directory=None):
    """Reject links/reparse points in every existing path component."""
    return _plain_path_info(path, directory=directory)[0]


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


def _checkpoint(check):
    if check is not None:
        check()


def _tree(root, *, source=False, checkpoint=None):
    _checkpoint(checkpoint)
    root = _plain_path(root, directory=True)
    found = {}
    total = 0

    def walk(directory):
        nonlocal total
        _checkpoint(checkpoint)
        for entry in sorted(directory.iterdir()):
            _checkpoint(checkpoint)
            path, info = _plain_path_info(entry)
            if stat.S_ISDIR(info.st_mode):
                if source and path.name in {'__pycache__', 'build'}:
                    continue
                walk(path)
            else:
                if source and path.suffix != '.py':
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise BundleError('parser_bundle_link_forbidden')
                if path.suffix != '.py' or info.st_size > MAX_FILE_BYTES:
                    raise BundleError('parser_bundle_integrity_failed')
                relative = path.relative_to(root).as_posix()
                _checked_relative(relative)
                _checkpoint(checkpoint)
                with path.open('rb') as stream:
                    _checkpoint(checkpoint)
                    # Recheck the actual opened object, not a second path walk.
                    # A same-content replacement or newly added hardlink must
                    # not pass merely because its bytes still match a manifest.
                    opened = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                            or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                        raise BundleError('parser_bundle_link_forbidden')
                    data = stream.read(MAX_FILE_BYTES + 1)
                _checkpoint(checkpoint)
                if len(data) > MAX_FILE_BYTES:
                    raise BundleError('parser_bundle_integrity_failed')
                total += len(data)
                if total > MAX_TOTAL_BYTES or len(found) >= MAX_FILES:
                    raise BundleError('parser_bundle_too_large')
                found[relative] = data
    walk(root)
    _checkpoint(checkpoint)
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
                or set(parsers) not in (set(_LEGACY_SOURCES), set(_NHTSA_SOURCES), set(_SOURCES), set(_DOCUMENT_SOURCES), set(_BRIDGESTONE_SOURCES), set(_CONTINENTAL_SOURCES), set(_GOODYEAR_SOURCES), set(_SAFETY_GATE_SOURCES), set(_YOKOHAMA_SOURCES), set(_DUNLOP_SOURCES), set(_SAMR_SOURCES))):
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
        if 'bridgestone-jp' in parsers:
            required.add('adapters/bridgestone.py')
        if 'continental-cn' in parsers:
            required.add('adapters/continental.py')
        if 'goodyear-sg' in parsers:
            required.add('adapters/goodyear.py')
        if 'eu-safety-gate' in parsers:
            required.add('adapters/safety_gate.py')
        if 'yokohama-eu' in parsers:
            required.add('adapters/yokohama.py')
        if 'dunlop-eu' in parsers:
            required.add('adapters/dunlop.py')
        if 'samr-cn-recalls' in parsers:
            required.add('adapters/samr.py')
        if 'workspace-pdf-text' in parsers:
            required.add('document_pdf.py')
        if not required <= set(files) or total > MAX_TOTAL_BYTES:
            raise BundleError('parser_bundle_manifest_invalid')
        for source, item in parsers.items():
            if (not isinstance(item, dict) or set(item) != {'parser_version', 'target_kind'}
                    or item['target_kind'] != _SAMR_SOURCES[source]
                    or not isinstance(item['parser_version'], str)
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._@+-]{0,99}', item['parser_version'])):
                raise BundleError('parser_bundle_manifest_invalid')
        if ('workspace-pdf-text' in parsers
                and parsers['workspace-pdf-text']['parser_version'] != 'workspace-pdf-text@1'):
            raise BundleError('parser_bundle_manifest_invalid')
        if (parsers['xiaomi-cn-vehicles']['parser_version'] in XIAOMI_PDF_PARSER_VERSIONS
                and XIAOMI_PDF_MAPPING_FILE not in files):
            raise BundleError('parser_bundle_manifest_invalid')
        return manifest
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise BundleError('parser_bundle_manifest_invalid') from None


def verify_tree(package_root, manifest, *, checkpoint=None):
    """Files must match exactly; extra caches/code cannot affect imports."""
    if _metadata(_tree(package_root, checkpoint=checkpoint)) != manifest['files']:
        raise BundleError('parser_bundle_integrity_failed')
    _checkpoint(checkpoint)


def copy_verified(package_root, manifest, destination, *, source=False, checkpoint=None):
    values = _tree(package_root, source=source, checkpoint=checkpoint)
    if _metadata(values) != manifest['files']:
        raise BundleError('parser_bundle_integrity_failed')
    destination = _filesystem_path(destination)
    _checkpoint(checkpoint)
    destination.mkdir(parents=True, exist_ok=False)
    _plain_path(destination, directory=True)
    for name, data in values.items():
        _checkpoint(checkpoint)
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            _checkpoint(checkpoint)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _checkpoint(checkpoint)
    verify_tree(destination, manifest, checkpoint=checkpoint)
    if _metadata(_tree(package_root, source=source, checkpoint=checkpoint)) != manifest['files']:
        raise BundleError('parser_bundle_integrity_failed')
    _checkpoint(checkpoint)


def _store_root(*, create=False):
    root = _filesystem_path(os.getenv('TI_PARSER_BUNDLE_ROOT') or 'data/parser-bundles')
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


def verify_bundle(manifest, *, checkpoint=None):
    _checkpoint(checkpoint)
    runtime = _policy()
    manifest = checked_manifest(manifest, protocol=runtime.PROTOCOL, limits=runtime.limits())
    _checkpoint(checkpoint)
    try:
        root = _store_root() / 'sha256' / manifest['bundle_id']
        _plain_path(root, directory=True)
        if {path.name for path in root.iterdir()} != {'manifest.json', 'package'}:
            raise BundleError('parser_bundle_integrity_failed')
        stored = _plain_path(root / 'manifest.json', directory=False)
        _checkpoint(checkpoint)
        with stored.open('rb') as stream:
            _checkpoint(checkpoint)
            stored_bytes = stream.read(128 * 1024 + 1)
        _checkpoint(checkpoint)
        if len(stored_bytes) > 128 * 1024 or stored_bytes != canonical(manifest):
            raise BundleError('parser_bundle_integrity_failed')
        package = _plain_path(root / 'package', directory=True)
        if {path.name for path in package.iterdir()} != {'tire_api'}:
            raise BundleError('parser_bundle_integrity_failed')
        package_root = package / 'tire_api'
        verify_tree(package_root, manifest, checkpoint=checkpoint)
        return {'bundle_id': manifest['bundle_id'], 'manifest': manifest, 'package_root': package_root}
    except BundleError:
        raise
    except OSError:
        raise BundleError('parser_bundle_storage_unavailable') from None


def bundle_descriptor(manifest, source_id):
    runtime = _policy()
    checked = checked_manifest(manifest, protocol=runtime.PROTOCOL, limits=runtime.limits())
    return runtime.descriptor_for_manifest(checked, source_id)
