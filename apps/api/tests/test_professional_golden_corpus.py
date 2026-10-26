"""Pure filesystem corpus boundaries. No app, database, provider or network imports."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tire_api.professional_golden_corpus import (MAX_EXTERNAL_BYTES, ProfessionalGoldenCorpus,
    ProfessionalGoldenCorpusError, strict_json_loads)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def row(path, raw, role='case'):
    return {'path': path, 'role': role, 'byte_count': len(raw), 'sha256': sha(raw)}


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / 'corpus'
    root.mkdir()
    cases = [encoded({'case_id': 'a', 'unknown': None, 'flag': False, 'value': 1}),
             encoded({'case_id': 'b', 'raw_value': '-0', 'value': 2})]
    files = [row('a.json', cases[0]), row('b.json', cases[1]), row('README.md', b'engineering only', 'readme')]
    for item, raw in zip(files, [*cases, b'engineering only']):
        (root / item['path']).write_bytes(raw)
    manifest = {'schema': 'professional-test-bridge-corpus@1', 'files': files,
        'case_ids': ['a', 'b'], 'human_truth_qualification': 'pending_external_review', 'external_refs': []}
    def save(raw=None):
        data = encoded(manifest) if raw is None else raw
        (root / 'manifest.json').write_bytes(data)
        return ProfessionalGoldenCorpus(root=root, expected_manifest_sha256=sha(data))
    return SimpleNamespace(root=root, manifest=manifest, save=save, reader=save())


def rejected(call, code=None):
    with pytest.raises(ProfessionalGoldenCorpusError) as caught:
        call()
    assert str(caught.value) == caught.value.code
    assert caught.value.code.startswith('professional_golden_')
    if code:
        assert caught.value.code == 'professional_golden_' + code
    return caught.value.code


def test_bound_reads_preserve_raw_objects_and_do_not_grant_human_truth(corpus):
    receipt = corpus.reader.verify_all()
    assert receipt['human_truth_qualification'] == 'pending_external_review'
    assert receipt['external_refs_verified'] is False
    assert receipt['case_ids'] == ['a', 'b'] and len(receipt['files']) == 3
    first = corpus.reader.read_case('a')
    assert first['unknown'] is None and first['flag'] is False and type(first['value']) is int
    first['flag'] = 'changed'
    assert corpus.reader.read_case('a')['flag'] is False
    assert corpus.reader.read_cases()[1]['raw_value'] == '-0'
    rejected(lambda: corpus.reader.read_case('absent'), 'case_not_found')


@pytest.mark.parametrize('path', ['', '.', '..', '../a.json', '/a.json', 'a//b.json',
    'a/./b.json', 'a/../b.json', 'C:/a.json', 'C:a.json', 'a\\b.json', 'a.json:stream',
    'a./b.json', 'a /b.json', 'NUL.json', 'sub/COM1.json', 'a\x00.json'])
def test_nonportable_or_escaping_paths_are_rejected_before_read(corpus, path):
    corpus.manifest['files'][0]['path'] = path
    rejected(corpus.save().verify_all, 'json_invalid' if '\x00' in path else 'path_invalid')


@pytest.mark.parametrize('mutation', ['bool_count', 'float_count', 'str_count', 'extra_key',
    'human_claim', 'duplicate_path', 'case_alias', 'duplicate_case', 'extra_ref_key', 'bad_sha'])
def test_manifest_is_closed_and_strict(corpus, mutation):
    value = corpus.manifest
    if mutation.endswith('_count'):
        value['files'][0]['byte_count'] = {'bool_count': True, 'float_count': 1.0, 'str_count': '1'}[mutation]
    elif mutation == 'extra_key':
        value['trusted_human'] = True
    elif mutation == 'human_claim':
        value['human_truth_qualification'] = 'human_reviewed'
    elif mutation == 'duplicate_path':
        value['files'].append(dict(value['files'][0]))
    elif mutation == 'case_alias':
        value['files'][1]['path'] = 'A.json'
    elif mutation == 'duplicate_case':
        value['case_ids'] = ['a', 'a']
    elif mutation == 'extra_ref_key':
        value['external_refs'] = [{'ref_id': 'x', 'path': 'x.pdf', 'byte_count': 0,
            'sha256': sha(b''), 'approved': True}]
    else:
        value['files'][0]['sha256'] = 'F' * 64
    rejected(corpus.save().verify_all, 'manifest_invalid')


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'{"x":1e999}', b'{"x":"\\ud800"}', b'\xff',
    b'\xef\xbb\xbf{}', b'[' * 30 + b'0' + b']' * 30, b'{"x":"\\u0000"}', 'not bytes'])
def test_strict_json_rejects_ambiguous_nonfinite_invalid_and_deep_input(raw):
    rejected(lambda: strict_json_loads(raw), 'json_invalid')


def test_strict_json_keeps_missing_null_boolean_integer_and_decimal_strings_distinct():
    value = strict_json_loads(b'{"null":null,"false":false,"zero":0,"text":"false","raw":"-0"}')
    assert 'missing' not in value and value['null'] is None
    assert value['false'] is False and type(value['zero']) is int
    assert value['text'] == 'false' and value['raw'] == '-0'


def test_pinned_manifest_drift_and_pending_pin_never_load(corpus):
    corpus.manifest['case_ids'].reverse()
    corpus.save()
    rejected(corpus.reader.verify_all, 'manifest_changed')
    rejected(lambda: ProfessionalGoldenCorpus(corpus.root, expected_manifest_sha256='pending').read_cases(), 'manifest_unpinned')


@pytest.mark.parametrize('target', ['b.json', 'README.md'])
def test_same_length_change_in_an_unread_file_blocks_every_case_read(corpus, target):
    path = corpus.root / target
    raw = path.read_bytes()
    changed = bytes([raw[0] ^ 1]) + raw[1:]
    assert len(changed) == len(raw)
    path.write_bytes(changed)
    rejected(lambda: corpus.reader.read_case('a'), 'file_binding_mismatch')


def test_unregistered_files_and_deleted_registered_files_are_not_ignored(corpus):
    extra = corpus.root / 'unregistered-secret.txt'
    extra.write_text('DO_NOT_ECHO_ME', encoding='utf-8')
    rejected(lambda: corpus.reader.read_case('a'), 'inventory_mismatch')
    extra.unlink()
    (corpus.root / 'b.json').unlink()
    rejected(corpus.reader.verify_all, 'inventory_mismatch')


def test_case_id_set_and_duplicate_json_keys_are_verified_independently(corpus):
    raw = b'{"case_id":"b","case_id":"a"}'
    (corpus.root / 'a.json').write_bytes(raw)
    corpus.manifest['files'][0] = row('a.json', raw)
    rejected(corpus.save().read_cases, 'json_invalid')
    raw = encoded({'case_id': 'b'})
    (corpus.root / 'a.json').write_bytes(raw)
    corpus.manifest['files'][0] = row('a.json', raw)
    rejected(corpus.save().read_cases, 'case_ids_mismatch')


def test_manifest_duplicate_key_is_rejected_even_under_matching_pin(corpus):
    raw = encoded(corpus.manifest)
    raw = b'{"schema":"professional-test-bridge-corpus@1",' + raw[1:]
    rejected(corpus.save(raw).verify_all, 'json_invalid')


def test_json_and_file_byte_limits_are_checked_before_parsing(corpus, monkeypatch):
    import tire_api.professional_golden_corpus as module
    rejected(lambda: strict_json_loads(b' ' * (module.MAX_JSON_BYTES + 1)), 'json_invalid')
    monkeypatch.setattr(module, 'MAX_JSON_BYTES', 10)
    rejected(corpus.reader.verify_all, 'file_too_large')


def symlink(target, path, *, directory=False):
    try:
        os.symlink(target, path, target_is_directory=directory)
    except (OSError, NotImplementedError):
        if directory and os.name == 'nt':
            try:
                import _winapi
                _winapi.CreateJunction(str(target), str(path))
                return
            except OSError:
                pass
        pytest.skip('Host does not permit an actual filesystem symlink/junction')


def test_registered_symlink_and_external_symlink_escape_are_rejected(corpus, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    raw = (corpus.root / 'a.json').read_bytes()
    (outside / 'a.json').write_bytes(raw)
    (corpus.root / 'a.json').unlink()
    corpus.manifest['files'][0]['path'] = 'linked/a.json'
    reader = corpus.save()
    symlink(outside, corpus.root / 'linked', directory=True)
    rejected(reader.verify_all, 'path_invalid')


def test_unregistered_directory_symlink_is_not_traversed(corpus, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    symlink(outside, corpus.root / 'escape', directory=True)
    rejected(corpus.reader.verify_all, 'path_invalid')


def external(corpus, raw=b'%PDF-1.4 synthetic external binding', path='paper.pdf'):
    corpus.manifest['external_refs'] = [{'ref_id': 'source-a', 'path': path,
        'byte_count': len(raw), 'sha256': sha(raw)}]
    return corpus.save()


def test_external_references_are_not_automatically_opened_and_return_no_content(corpus, tmp_path):
    raw = b'%PDF-1.4 synthetic external binding'
    reader = external(corpus, raw)
    assert reader.read_case('a')['case_id'] == 'a'
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    rejected(lambda: reader.verify_external(evidence), 'external_verification_failed')
    (evidence / 'paper.pdf').write_bytes(raw)
    result = reader.verify_external(evidence)
    assert result == [{'ref_id': 'source-a', 'path': 'paper.pdf', 'byte_count': len(raw),
                       'sha256': sha(raw), 'exists': True}]
    (evidence / 'paper.pdf').write_bytes(raw[:-1] + b'!')
    rejected(lambda: reader.verify_external(evidence), 'external_verification_failed')


@pytest.mark.parametrize('path', ['.env', '.env.json', '.aws/key.json', 'credentials.json',
    'secrets.json', 'private.key', 'private.key.json', 'snapshot.db', 'snapshot.sqlite.json',
    'snapshot.sqlite3-wal.json', 'a.pem.pdf', 'readme.txt'])
def test_external_sensitive_or_unsupported_types_are_rejected_without_opening(corpus, path):
    rejected(external(corpus, path=path).verify_all, 'external_path_forbidden')


def test_external_path_escape_symlink_and_size_limit_are_rejected(corpus, tmp_path):
    rejected(external(corpus, path='../outside.pdf').verify_all, 'path_invalid')
    raw = b'%PDF-1.4 bound synthetic bytes'
    reader = external(corpus, raw, 'linked/paper.pdf')
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'paper.pdf').write_bytes(raw)
    corpus.manifest['external_refs'][0]['byte_count'] = MAX_EXTERNAL_BYTES + 1
    rejected(corpus.save().verify_all, 'manifest_invalid')
    reader = external(corpus, raw, 'linked/paper.pdf')
    symlink(outside, evidence / 'linked', directory=True)
    rejected(lambda: reader.verify_external(evidence), 'external_verification_failed')
