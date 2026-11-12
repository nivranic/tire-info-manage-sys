"""Evaluate saved normal knowledge-search responses against independent labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--actuals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from pydantic import ValidationError
    from tire_api.professional_golden_corpus import strict_json_loads
    from tire_api.retrieval_evaluation import EvaluationActuals, EvaluationCorpus, evaluate

    try:
        inputs = []
        bindings = {}
        for name, path in [('corpus', args.corpus), ('actuals', args.actuals)]:
            with path.open('rb') as stream:
                raw = stream.read(512_001)
            inputs.append(strict_json_loads(raw))
            bindings[name] = {'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        result = evaluate(EvaluationCorpus.model_validate(inputs[0]), EvaluationActuals.model_validate(inputs[1]))
        result['input_bindings'] = bindings
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        print(json.dumps({'state': result['state'], 'case_count': result['case_count'],
                          'constraints_passed': result['constraints_passed']}))
        return 0 if result['constraints_passed'] else 2
    except (ValidationError, OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'error_code': 'retrieval_evaluation_input_invalid'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
