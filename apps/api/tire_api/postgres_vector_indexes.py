"""Explicit HNSW declarations and owner maintenance against an approved schema."""
import json
import re
import sys

from .external_fact_governance import GovernanceError
from .external_fact_governance_cli import _Parser, _password, _request
from .external_fact_governance_postgres import postgres_connect_args, postgres_engine
from .postgres_schema import (SchemaContractError, _settings, capture_schema,
                              load_contract, source_fingerprint)


def index_name(space):
    return 'ix_embedding_hnsw_' + space[:24]


def checked_indexes(indexes):
    if not isinstance(indexes, (list, tuple)) or len(indexes) > 32:
        raise SchemaContractError('vector_index_manifest_invalid')
    names, result = set(), []
    for item in indexes:
        if type(item) is not dict or item.keys() != {'model_space', 'dimensions'}:
            raise SchemaContractError('vector_index_manifest_invalid')
        space, dimensions = item['model_space'], item['dimensions']
        if (type(space) is not str or re.fullmatch('[0-9a-f]{64}', space) is None
                or type(dimensions) is not int or not 1 <= dimensions <= 2000
                or index_name(space) in names):
            raise SchemaContractError('vector_index_manifest_invalid')
        names.add(index_name(space))
        result.append({'model_space': space, 'dimensions': dimensions})
    return tuple(sorted(result, key=lambda item: item['model_space']))


def load_index_manifest(path):
    value = _request(path)
    if (type(value) is not dict or value.keys() != {'schema', 'indexes'}
            or value['schema'] != 'postgres-vector-indexes@1'):
        raise SchemaContractError('vector_index_manifest_invalid')
    return checked_indexes(value['indexes'])


def index_sql(space, dimensions, *, if_not_exists=False):
    checked_indexes([{'model_space': space, 'dimensions': dimensions}])
    clause = 'IF NOT EXISTS ' if if_not_exists else ''
    return (f'CREATE INDEX {clause}{index_name(space)} ON public.embedding_vectors '
            f'USING hnsw ((embedding::public.vector({dimensions})) public.vector_cosine_ops) '
            f"WHERE model_space = '{space}' AND dimensions = {dimensions}")


def create_reference_indexes(connection, indexes):
    indexes = checked_indexes(indexes)
    if indexes and connection.exec_driver_sql("SELECT to_regtype('public.vector') IS NOT NULL").scalar() is not True:
        raise SchemaContractError('vector_index_extension_required')
    for item in indexes:
        connection.exec_driver_sql(index_sql(item['model_space'], item['dimensions']))


def maintain_indexes(engine, contract_path, contract_sha256, indexes):
    indexes = checked_indexes(indexes)
    expected = load_contract(contract_path, contract_sha256)
    declared = {(item['model_space'], item['dimensions']) for item in expected['vector_indexes']}
    wanted = {row[1]: row for row in expected['catalog']['indexes'] if row[0] == 'embedding_vectors'}
    names = [index_name(item['model_space']) for item in indexes]
    if (any(name not in wanted for name in names)
            or any((item['model_space'], item['dimensions']) not in declared for item in indexes)):
        raise SchemaContractError('vector_index_not_declared')
    created = 0
    with engine.begin() as connection:
        major = _settings(connection)
        owner = connection.exec_driver_sql("SELECT pg_has_role(current_user,c.relowner,'USAGE') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname='embedding_vectors' AND c.relkind='r'").scalar()
        if owner is not True:
            raise SchemaContractError('vector_index_owner_required')
        current = capture_schema(connection)
        existing = {row[1]: row for row in current['indexes']}
        missing = [item for item in indexes if index_name(item['model_space']) not in existing]
        # Only the exact requested, approved missing indexes may differ.
        current['indexes'] = sorted(current['indexes'] + [wanted[index_name(item['model_space'])]
            for item in missing], key=lambda row: (row[0], row[1]))
        if major != expected['postgres_major'] or current != expected['catalog']:
            raise SchemaContractError('schema_contract_mismatch')
        for item in missing:
            connection.exec_driver_sql(index_sql(item['model_space'], item['dimensions']))
            created += 1
        if capture_schema(connection) != expected['catalog']:
            raise SchemaContractError('schema_contract_mismatch')
        if source_fingerprint() != expected['source_sha256']:
            raise SchemaContractError('schema_contract_source_changed')
    return {'schema': 'postgres-vector-maintenance@1', 'created': created,
            'existing': len(indexes) - created}


def main(argv=None):
    engine = None
    result = {'ok': False, 'code': 'vector_index_maintenance_failed'}
    try:
        parser = _Parser(description='Maintain declared HNSW indexes against an approved empty-reference contract.')
        parser.add_argument('--postgres-profile', required=True)
        parser.add_argument('--vector-indexes-file', required=True)
        parser.add_argument('--schema-contract', required=True)
        parser.add_argument('--schema-sha256', required=True)
        args = parser.parse_args(argv)
        if not sys.stdin.isatty():
            raise GovernanceError('interactive_authentication_required')
        indexes = load_index_manifest(args.vector_indexes_file)
        load_contract(args.schema_contract, args.schema_sha256)
        parameters = postgres_connect_args(_request(args.postgres_profile))
        password = _password('Index owner PostgreSQL password: ')
        try:
            engine = postgres_engine(parameters, password)
        finally:
            del password
        result = {'ok': True, **maintain_indexes(engine, args.schema_contract, args.schema_sha256, indexes)}
    except (SchemaContractError, GovernanceError) as error:
        result = {'ok': False, 'code': error.code}
    except (Exception, KeyboardInterrupt):
        result = {'ok': False, 'code': 'vector_index_maintenance_failed'}
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                result = {'ok': False, 'code': 'vector_index_maintenance_failed'}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
