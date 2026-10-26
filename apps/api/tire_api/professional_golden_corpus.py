"""Pinned, closed corpus I/O; no application, database or Golden semantics."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

CORPUS_ROOT = Path(__file__).resolve().parents[3] / 'packages/domain-types/fixtures/professional-test-bridge-v1'
MANIFEST_SHA256 = 'd222b70c14dc09584f06590902fd13eac9559ac72e3d1a203adc35c341eb91f2'
MAX_JSON_BYTES = 512_000
MAX_FILE_BYTES = 512_000
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_EXTERNAL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 300
MAX_DEPTH = 24
_SHA = re.compile(r'^[0-9a-f]{64}$')
_RESERVED = re.compile(r'^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$', re.I)


class ProfessionalGoldenCorpusError(ValueError):
    """Fixed codes only: never echo rejected content, filenames or secrets."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise ProfessionalGoldenCorpusError('professional_golden_' + code)


def _pairs(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            _fail('json_invalid')
        value[key] = child
    return value


def _tree(value, depth=0):
    if depth > MAX_DEPTH:
        _fail('json_invalid')
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail('json_invalid')
        return
    if type(value) is str:
        value.encode('utf-8', errors='strict')
        if '\x00' in value:
            _fail('json_invalid')
        return
    if type(value) is list:
        for child in value:
            _tree(child, depth + 1)
        return
    if type(value) is dict:
        for key, child in value.items():
            _tree(key, depth + 1)
            _tree(child, depth + 1)
        return
    _fail('json_invalid')


def _json(raw):
    if type(raw) is not bytes or len(raw) > MAX_JSON_BYTES:
        _fail('json_invalid')
    def constant(_value):
        _fail('json_invalid')
    try:
        value = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=_pairs,
                           parse_constant=constant)
        _tree(value)
        return value
    except ProfessionalGoldenCorpusError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        _fail('json_invalid')


def strict_json_loads(raw: bytes):
    """Decode bounded UTF-8 bytes without duplicate keys, nonfinite values or coercion."""
    return _json(raw)


def _object(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _fail('manifest_invalid')


def _label(value):
    if (type(value) is not str or not value or value != value.strip() or len(value) > 120
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail('manifest_invalid')
    return value


def _path(value):
    if (type(value) is not str or not value or len(value) > 512 or '\\' in value
            or any(ord(char) < 32 or ord(char) == 127 or char in ':<>"|?*' for char in value)):
        _fail('path_invalid')
    parts = value.split('/')
    if any(part in ('', '.', '..') or part[-1:] in ('.', ' ')
           or _RESERVED.fullmatch(part.split('.', 1)[0]) for part in parts):
        _fail('path_invalid')
    return value


def _bound_row(row, keys, maximum):
    _object(row, keys)
    _path(row['path'])
    if (type(row['byte_count']) is not int or not 0 <= row['byte_count'] <= maximum
            or type(row['sha256']) is not str or not _SHA.fullmatch(row['sha256'])):
        _fail('manifest_invalid')


def _link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _root(value):
    try:
        path = Path(value).absolute()
        if _link(path) or not path.is_dir():
            _fail('path_invalid')
        return path.resolve(strict=True)
    except ProfessionalGoldenCorpusError:
        raise
    except (OSError, ValueError, TypeError):
        _fail('path_invalid')


def _file(root, name):
    _path(name)
    path = root.joinpath(*name.split('/'))
    try:
        current = root
        for part in name.split('/'):
            current /= part
            if _link(current):
                _fail('path_invalid')
        if not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
            _fail('path_invalid')
        return path
    except ProfessionalGoldenCorpusError:
        raise
    except (OSError, ValueError):
        _fail('file_unavailable')


def _read(root, name, maximum, *, content=False):
    path = _file(root, name)
    try:
        before = path.stat()
        if before.st_size > maximum:
            _fail('file_too_large')
        digest, size, chunks = hashlib.sha256(), 0, []
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                _fail('file_changed')
            while chunk := stream.read(min(65536, maximum + 1 - size)):
                size += len(chunk)
                if size > maximum:
                    _fail('file_too_large')
                digest.update(chunk)
                if content:
                    chunks.append(chunk)
            after_open = os.fstat(stream.fileno())
        after = _file(root, name).stat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if identity(before) != identity(after) or identity(opened) != identity(after_open) or size != before.st_size:
            _fail('file_changed')
        return {'path': name, 'byte_count': size, 'sha256': digest.hexdigest()}, b''.join(chunks) if content else None
    except ProfessionalGoldenCorpusError:
        raise
    except (OSError, ValueError):
        _fail('file_unavailable')


def _inventory(root):
    result = set()
    def visit(directory):
        for path in directory.iterdir():
            if _link(path):
                _fail('path_invalid')
            if path.is_dir():
                visit(path)
            elif path.is_file():
                name = path.relative_to(root).as_posix()
                _path(name)
                result.add(name)
            else:
                _fail('path_invalid')
    try:
        visit(root)
        return result
    except ProfessionalGoldenCorpusError:
        raise
    except (OSError, ValueError, RecursionError):
        _fail('file_unavailable')


def _manifest(value):
    _object(value, ('schema', 'files', 'case_ids', 'human_truth_qualification', 'external_refs'))
    if (value['schema'] != 'professional-test-bridge-corpus@1'
            or value['human_truth_qualification'] != 'pending_external_review'):
        _fail('manifest_invalid')
    for key in ('files', 'case_ids', 'external_refs'):
        if type(value[key]) is not list or len(value[key]) > MAX_ENTRIES:
            _fail('manifest_invalid')
    if not value['files'] or not value['case_ids']:
        _fail('manifest_invalid')
    paths, ids = set(), set()
    for row in value['files']:
        _bound_row(row, ('path', 'role', 'byte_count', 'sha256'), MAX_FILE_BYTES)
        if row['role'] not in ('case', 'readme') or type(row['role']) is not str:
            _fail('manifest_invalid')
        if row['path'].casefold() == 'manifest.json' or row['path'].casefold() in paths:
            _fail('manifest_invalid')
        if (row['role'] == 'case' and not row['path'].endswith('.json')):
            _fail('manifest_invalid')
        paths.add(row['path'].casefold())
    if sum(row['byte_count'] for row in value['files']) > MAX_TOTAL_BYTES:
        _fail('manifest_invalid')
    for case_id in value['case_ids']:
        _label(case_id)
        if case_id in ids:
            _fail('manifest_invalid')
        ids.add(case_id)
    refs, external_paths = set(), set()
    for row in value['external_refs']:
        _bound_row(row, ('ref_id', 'path', 'byte_count', 'sha256'), MAX_EXTERNAL_BYTES)
        _label(row['ref_id'])
        if row['ref_id'] in refs or row['path'].casefold() in external_paths:
            _fail('manifest_invalid')
        refs.add(row['ref_id'])
        external_paths.add(row['path'].casefold())
        path = Path(row['path'])
        if (path.suffix.lower() not in ('.pdf', '.json')
                or any(part.lower() in ('.aws', '.ssh', 'credentials') for part in path.parts)
                or any(part.lower().startswith('.env') for part in path.parts)
                or re.search(r'\.(?:db|sqlite3?|key|pem|p12|pfx)(?:$|[.\-])', path.name, re.I)
                or path.name.lower() in ('credentials.json', 'secrets.json')):
            _fail('external_path_forbidden')
    return value


class ProfessionalGoldenCorpus:
    def __init__(self, root=CORPUS_ROOT, expected_manifest_sha256=MANIFEST_SHA256):
        self.root = Path(root)
        self.expected_manifest_sha256 = expected_manifest_sha256

    def _verify(self):
        pin = self.expected_manifest_sha256
        if type(pin) is not str or not _SHA.fullmatch(pin):
            _fail('manifest_unpinned')
        root = _root(self.root)
        manifest_binding, raw = _read(root, 'manifest.json', MAX_JSON_BYTES, content=True)
        if manifest_binding['sha256'] != pin:
            _fail('manifest_changed')
        manifest = _manifest(_json(raw))
        expected = {row['path'] for row in manifest['files']} | {'manifest.json'}
        if _inventory(root) != expected:
            _fail('inventory_mismatch')
        cases, bound = {}, []
        for row in manifest['files']:
            actual, content = _read(root, row['path'], MAX_FILE_BYTES, content=row['role'] == 'case')
            if actual['byte_count'] != row['byte_count'] or actual['sha256'] != row['sha256']:
                _fail('file_binding_mismatch')
            bound.append(actual | {'role': row['role']})
            if row['role'] == 'case':
                case = _json(content)
                if type(case) is not dict or type(case.get('case_id')) is not str or case['case_id'] not in manifest['case_ids'] or case['case_id'] in cases:
                    _fail('case_ids_mismatch')
                cases[case['case_id']] = case
        if set(cases) != set(manifest['case_ids']):
            _fail('case_ids_mismatch')
        if _inventory(root) != expected or _read(root, 'manifest.json', MAX_JSON_BYTES)[0] != manifest_binding:
            _fail('manifest_changed')
        receipt = {'schema': 'professional-test-bridge-corpus-verification@1',
            'manifest_sha256': pin, 'human_truth_qualification': 'pending_external_review',
            'case_ids': manifest['case_ids'], 'files': bound, 'external_refs': manifest['external_refs'],
            'external_refs_verified': False}
        return receipt, cases, manifest

    def verify_all(self):
        return deepcopy(self._verify()[0])

    def read_cases(self):
        receipt, cases, _manifest_value = self._verify()
        return [deepcopy(cases[case_id]) for case_id in receipt['case_ids']]

    def read_case(self, case_id):
        _receipt, cases, _manifest_value = self._verify()
        if type(case_id) is not str or case_id not in cases:
            _fail('case_not_found')
        return deepcopy(cases[case_id])

    def verify_external(self, evidence_root):
        _receipt, _cases, manifest = self._verify()
        root = _root(evidence_root)
        result = []
        for row in manifest['external_refs']:
            try:
                actual, _content = _read(root, row['path'], MAX_EXTERNAL_BYTES)
                if actual['byte_count'] != row['byte_count'] or actual['sha256'] != row['sha256']:
                    _fail('external_binding_mismatch')
            except ProfessionalGoldenCorpusError:
                _fail('external_verification_failed')
            result.append(actual | {'ref_id': row['ref_id'], 'exists': True})
        return result
