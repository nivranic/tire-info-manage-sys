"""Build a reviewed schema contract in an explicit, empty PostgreSQL reference."""
import json
import sys

from .external_fact_governance import GovernanceError
from .external_fact_governance_cli import _Parser, _password, _request
from .external_fact_governance_postgres import postgres_connect_args, postgres_engine
from .postgres_schema import SchemaContractError, build_reference


def main(argv=None):
    engine = None
    result = {'ok': False, 'code': 'schema_reference_failed'}
    try:
        parser = _Parser(description='Migrate an empty reference database and publish a new schema contract.')
        parser.add_argument('--postgres-profile', required=True)
        parser.add_argument('--output-file', required=True)
        parser.add_argument('--empty-reference-confirmed', action='store_true', required=True)
        args = parser.parse_args(argv)
        if not sys.stdin.isatty():
            raise GovernanceError('interactive_authentication_required')
        parameters = postgres_connect_args(_request(args.postgres_profile))
        password = _password('Reference PostgreSQL password: ')
        try:
            engine = postgres_engine(parameters, password)
        finally:
            del password
        result = {'ok': True, **build_reference(engine, args.output_file)}
    except (SchemaContractError, GovernanceError) as error:
        result = {'ok': False, 'code': error.code}
    except (Exception, KeyboardInterrupt):
        result = {'ok': False, 'code': 'schema_reference_failed'}
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                result = {'ok': False, 'code': 'schema_reference_failed'}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
