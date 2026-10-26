"""Verify bound professional Golden snapshots offline; human qualification stays pending."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def fingerprint():
    names = ['apps/api/tire_api/professional_golden_checks.py',
             'apps/api/tire_api/professional_golden_corpus.py']
    return hashlib.sha256(json.dumps({name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in names}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_actuals(directory):
    from tire_api.professional_golden_corpus import strict_json_loads, ProfessionalGoldenCorpusError
    def bad():
        raise ProfessionalGoldenCorpusError('professional_golden_actual_directory_invalid')
    directory = directory.absolute()
    try:
        if directory.is_symlink() or not directory.is_dir():
            bad()
        if getattr(directory.lstat(), 'st_file_attributes', 0) & 0x400:
            bad()
        result, bindings, total = [], [], 0
        entries = sorted(directory.iterdir())
        if not 1 <= len(entries) <= 300:
            bad()
        for path in entries:
            if (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400
                    or not stat.S_ISREG(path.stat().st_mode) or path.suffix != '.json'
                    or not path.resolve().is_relative_to(directory.resolve())
                    or path.stat().st_size > 512_000):
                bad()
            before = path.stat()
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                if not stat.S_ISREG(opened.st_mode) or identity(before) != identity(opened):
                    bad()
                raw = stream.read(512_001)
                if len(raw) > 512_000 or identity(opened) != identity(os.fstat(stream.fileno())):
                    bad()
            if (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400
                    or identity(before) != identity(path.stat())):
                bad()
            total += len(raw)
            if total > 32_000_000:
                bad()
            value = strict_json_loads(raw)
            if type(value) is not dict or path.name != value.get('case_id', '') + '.json':
                bad()
            result.append(value)
            bindings.append({'path': path.name, 'byte_count': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest()})
        if sorted(directory.iterdir()) != entries:
            bad()
        return result, bindings
    except ProfessionalGoldenCorpusError:
        raise
    except (OSError, ValueError, TypeError):
        bad()


def verify(directory, external_root=None):
    from tire_api.professional_golden_checks import evaluate_corpus
    from tire_api.professional_golden_corpus import ProfessionalGoldenCorpus, MANIFEST_SHA256
    corpus = ProfessionalGoldenCorpus()
    receipt = corpus.verify_all()
    cases = corpus.read_cases()
    externals = None if external_root is None else corpus.verify_external(external_root)
    actuals, bindings = load_actuals(directory)
    contract = fingerprint()
    report = evaluate_corpus(cases, actuals, MANIFEST_SHA256, contract)
    report = report.model_dump(mode='json', by_alias=True) if hasattr(report, 'model_dump') else report
    if fingerprint() != contract or corpus.verify_all() != receipt or load_actuals(directory)[1] != bindings:
        from tire_api.professional_golden_corpus import ProfessionalGoldenCorpusError
        raise ProfessionalGoldenCorpusError('professional_golden_inputs_changed')
    return {'schema': 'professional-golden-offline-verification@1',
        'evaluation_mode': 'offline_bound_snapshot', 'report': report,
        'input_bindings': bindings, 'corpus_receipt': receipt,
        'external_evidence_bindings': externals,
        'notice': 'Bound archived bytes only; not live HTTP, latest state, licence authority or human qualification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-dir', required=True, type=Path)
    parser.add_argument('--verify-external-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-golden-gate', action='store_true')
    args = parser.parse_args()
    from tire_api.professional_golden_corpus import ProfessionalGoldenCorpusError
    from pydantic import ValidationError
    try:
        result = verify(args.actual_dir, args.verify_external_root)
        if args.output:
            # Do not replace prior evidence or any input; each receipt gets a new path.
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
        report = result['report']
        print(json.dumps({'state': report['state'], 'release_gate': report['release_gate'],
            'evaluation_mode': 'offline_bound_snapshot', 'human_truth_status': report['human_truth_status']}))
        if report['state'] == 'failed':
            return 1
        return 2 if args.require_golden_gate and report['release_gate'] != 'passed' else 0
    except ProfessionalGoldenCorpusError as error:
        print(json.dumps({'error_code': error.code}))
        return 1
    except (ValidationError, OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'error_code': 'professional_golden_verification_invalid'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
