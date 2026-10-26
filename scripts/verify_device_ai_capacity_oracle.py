"""Independent, standard-library oracle for the new synthetic device-AI corpus.

This script never imports product code. Its canonicalizer follows the written
specification using json's exact numeric-token hooks, rather than a product
parser/projector. It is only a test-data verifier, not a wire decoder or gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


class NumericToken(str):
    """A JSON numeric lexeme, never a binary floating-point approximation."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key in oracle input')
        result[key] = value
    return result


def exact_json(raw: bytes):
    # json.loads(bytes) accepts BOM; the test oracle intentionally does not.
    assert not raw.startswith(b'\xef\xbb\xbf'), 'BOM has no successful oracle AST'
    return json.loads(raw.decode('utf-8', errors='strict'), parse_int=NumericToken,
                      parse_float=NumericToken, object_pairs_hook=_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def canonical(value) -> bytes:
    if isinstance(value, NumericToken):
        return value.encode('ascii')
    if value is None:
        return b'null'
    if type(value) is bool:
        return b'true' if value else b'false'
    if type(value) is int:
        assert abs(value) <= 9007199254740991
        return str(value).encode('ascii')
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False).encode('utf-8')
    if type(value) is list:
        return b'[' + b','.join(canonical(item) for item in value) + b']'
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        return b'{' + b','.join(canonical(key) + b':' + canonical(value[key])
                                for key in sorted(value)) + b'}'
    raise TypeError('unsupported oracle input type')


def digest(raw: bytes, namespace: str | None = None) -> str:
    prefix = b'' if namespace is None else namespace.encode('utf-8') + b'\0'
    return hashlib.sha256(prefix + raw).hexdigest()


def selection_preimage(selectors):
    return sorted(selectors, key=lambda row: row['member_key'])


def preview_preimage(value):
    # fingerprint-spec section 4: requested order is meaningful, resolved is a set.
    return {'intent': {'purpose': 'device_history_analysis',
                       'policy_version': 'device-ai-projection@1',
                       'question_sha256': value['question_sha256'],
                       'include_context_ids': value['include_context_ids']},
            'projection_mode': value['projection_mode'], 'query_context': value['query_context'],
            'origin': value['origin'], 'selected': value['selected'],
            'resolved_closure': selection_preimage(value['resolved_closure']),
            'state': value['state'], 'projection_sha256': value['projection_sha256']}


def context_preimage(value):
    # fingerprint-spec section 3 excludes prepare_id and binding_verification.
    fields = ('package_id', 'package_schema', 'package_sha256', 'projection_mode',
              'projection_sha256', 'selection_sha256')
    result = {key: value[key] for key in fields}
    result.update(schema='device-ai-context@1', numeric_encoding='device-number-token@1')
    result['receipt_sources'] = sorted(value['receipt_sources'],
                                       key=lambda row: row['selector']['member_key'])
    result['device_citations'] = sorted(value['device_citations'], key=canonical)
    result['domain_boundaries'] = sorted(value['domain_boundaries'],
                                        key=lambda row: (row['kind'], canonical(row)))
    return result


def check_expected(preimage, expected, namespace):
    raw = canonical(preimage)
    assert raw == expected['canonical_text'].encode('utf-8'), 'literal preimage differs from specification'
    assert raw.hex() == expected['canonical_utf8_hex']
    assert len(raw) == expected['byte_count']
    assert digest(raw, namespace) == expected['sha256']


def verify_fingerprints(value):
    checked = 0
    for case in value['preview_cases']:
        check_expected(preview_preimage(case['input']), case['expected'], 'device-ai-local-preview@1')
        checked += 1
    check_expected(selection_preimage(value['selection_input']), value['selection_expected'],
                   'device-ai-selection@1')
    checked += 1
    contexts = value.get('context_cases', [value.get('context_case')])
    for case in contexts:
        check_expected(context_preimage(case['input']), case['expected'], 'device-ai-context@1')
        checked += 1
    pairs = {case['id']: case['expected']['sha256'] for case in value['preview_cases']}
    assert pairs['closure-ascending'] == pairs['closure-descending']
    assert pairs['closure-ascending'] != pairs['selected-order-change']
    # These scalar positions have opposite UTF-16-code-unit vs UTF-8-byte order.
    assert '\ue000'.encode('utf-8') < '\U00010000'.encode('utf-8')
    boundaries = context_preimage(contexts[0]['input'])['domain_boundaries']
    assert [row['boundary']['notice'] for row in boundaries] == ['\ue000', '\U00010000']
    return checked


def corpus_file(root: Path, name: str) -> Path:
    assert name and ':' not in name and '\\' not in name
    assert all(part not in {'', '.', '..'} for part in name.split('/'))
    path = root / name
    assert path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    assert not path.is_symlink()
    return path


def verify_boundary(root: Path):
    spec = json.loads(corpus_file(root, 'boundary-recipes.json').read_text(encoding='utf-8'))
    assert spec['schema'] == 'device-ai-capacity-recipes@1'
    assert spec['max_package_bytes'] == 8388608
    cases = []
    for case in spec['cases']:
        recipe = case['input']
        assert recipe['form'] == 'repeat_hex'
        repeat = bytes.fromhex(recipe['repeat_hex'])
        count = recipe['repeat_count']
        assert type(count) is int and 0 <= count <= 8388609 and len(repeat) <= 4
        raw = bytes.fromhex(recipe['prefix_hex']) + repeat * count + bytes.fromhex(recipe['suffix_hex'])
        assert len(raw) == case['input_byte_count'] and digest(raw) == case['input_sha256']
        expected = case['expected']
        if expected['state'] == 'accepted':
            assert 0 < len(raw) <= 8388608
            result = canonical(exact_json(raw))
            assert result == expected['canonical_text'].encode('utf-8')
            assert result.hex() == expected['canonical_utf8_hex']
            assert digest(result) == expected['canonical_sha256']
        else:
            assert expected['state'] == 'rejected'
            if not raw or len(raw) > 8388608:
                assert expected['error_code'] == 'device_ai_package_capacity'
            elif raw.startswith(b'\xef\xbb\xbf'):
                assert expected['error_code'] == 'device_ai_json_bom'
            else:
                try:
                    exact_json(raw)
                except UnicodeError:
                    assert expected['error_code'] == 'device_ai_json_utf8'
                except json.JSONDecodeError:
                    assert expected['error_code'] == 'device_ai_json_invalid'
                else:
                    raise AssertionError('Rejected recipe has no independent encoding/JSON error')
        cases.append({'id': case['id'], 'bytes': len(raw), 'sha256': digest(raw),
                      'expected_state': expected['state']})
    assert {8388607, 8388608, 8388609}.issubset({row['bytes'] for row in cases})
    return cases


def verify_corpus(root: Path):
    manifest_path = corpus_file(root, 'manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['schema'] == 'device-ai-capacity-corpus@1'
    assert manifest['synthetic_only'] and manifest['max_package_bytes'] == 8388608
    names = set()
    for entry in manifest['files']:
        assert entry['path'] not in names
        names.add(entry['path'])
        actual = record(corpus_file(root, entry['path']))
        assert actual['bytes'] == entry['byte_count'] and actual['sha256'] == entry['sha256']
    assert {'boundary-recipes.json', 'closure-fingerprints.json', 'formal-package.json'}.issubset(names)
    fingerprints = json.loads(corpus_file(root, 'closure-fingerprints.json').read_text(encoding='utf-8'))
    return {'manifest': record(manifest_path), 'bound_files': len(names),
            'fingerprint_literal_preimages_verified': verify_fingerprints(fingerprints),
            'raw_boundary_cases': verify_boundary(root), 'formal_package_cases': verify_formal(root)}


def verify_formal(root: Path):
    fixture = json.loads(corpus_file(root, 'formal-package.json').read_text(encoding='utf-8'))
    assert fixture['schema'] == 'device-ai-formal-capacity@1'
    base = corpus_file(root, fixture['base_pack']).read_bytes()
    # Reuse the historical literal as authority, never an executed projector.
    legacy = root.parent / 'device-ai-v1/projection-vectors-a/domain/nonempty-tire-single'
    source_input = (legacy / 'input.json').read_bytes()
    source_literal = (legacy / 'projection.canonical.json').read_bytes()
    assert digest(source_input) == 'd2f1f1ad761c6f100ada487c2abb83e4996c57f3751305df1320766e4763faf4'
    assert digest(source_literal) == 'e6c42637f571dfb6695ec470a9c80d77d7ab42a879eeec1d7354ca0a2b5144e8'
    assert corpus_file(root, fixture['projection_input']).read_bytes() == source_input
    assert canonical(exact_json(source_literal)) == source_literal
    old_sha = exact_json(source_literal)['archive']['sha256']
    assert old_sha == digest(base) and source_literal.count(old_sha.encode('ascii')) == 1
    rows = []
    for case in fixture['cases']:
        padding = case['padding_spaces']
        assert type(padding) is int and 0 <= padding <= 8388609
        raw = base + b' ' * padding
        assert len(raw) == case['input_byte_count'] and digest(raw) == case['input_sha256']
        if len(raw) <= 8388608:
            assert case['parser_expected'] == {'state': 'accepted'}
        else:
            assert case['parser_expected'] == {'state': 'rejected', 'error_code': 'device_ai_package_capacity'}
        expected = case['expected']
        if expected['state'] == 'accepted':
            assert 0 < len(raw) <= 8388608
            assert exact_json(raw) == exact_json(base)
            literal = corpus_file(root, expected['projection_file']).read_bytes()
            correct = source_literal.replace(old_sha.encode('ascii'), digest(raw).encode('ascii'))
            assert literal == correct, 'Derived projection must retain content and bind the actual raw SHA'
            assert canonical(exact_json(literal)) == literal
            assert len(literal) == expected['projection_byte_count']
            assert digest(literal) == expected['projection_sha256']
        else:
            assert expected['state'] == 'rejected' and len(raw) > 8388608
            assert expected['error_code'] == 'device_ai_metadata_number_invalid'
        rows.append({'id': case['id'], 'bytes': len(raw), 'sha256': digest(raw),
                     'expected_state': expected['state']})
    assert {8388607, 8388608, 8388609}.issubset({r['bytes'] for r in rows})
    return rows


def record(path: Path):
    raw = path.read_bytes()
    return {'path': path.as_posix(), 'bytes': len(raw), 'sha256': digest(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fingerprints', type=Path)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    assert bool(args.fingerprints) != bool(args.corpus), 'Choose fingerprints or corpus'
    if args.fingerprints:
        before = record(args.fingerprints)
        value = json.loads(args.fingerprints.read_text(encoding='utf-8'))
        checked = {'fingerprint_literal_preimages_verified': verify_fingerprints(value), 'input': before}
        assert record(args.fingerprints) == before
    else:
        checked = verify_corpus(args.corpus)
    result = {'schema': 'device-ai-capacity-independent-oracle@1',
              'captured_at': datetime.now(timezone.utc).isoformat(), 'outcome': 'passed',
              **checked,
              'oracle_source': record(Path(__file__)), 'product_imported': False,
              'network_database_services': False,
              'scope': 'specified synthetic literals and digest preimages; not a full wire or native runtime validator'}
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
