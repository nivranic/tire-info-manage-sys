"""Source-bound reference schema and read-only PostgreSQL runtime admission.

The reference is built from an empty, explicitly selected database. Runtime
never captures its own schema as an expected contract or repairs a mismatch.
"""
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import text


SCHEMA = 'postgres-runtime-schema@3'
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 20000
OVERSIZE = '__tire_schema_value_too_large__'


class SchemaContractError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def source_fingerprint():
    root = Path(__file__).resolve().parent
    files = sorted(root.rglob('*.py'))
    if not files or len(files) > 512:
        raise SchemaContractError('schema_source_invalid')
    values = []
    for path in files:
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise SchemaContractError('schema_source_invalid')
        values.append([path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()])
    return hashlib.sha256(_json(values)).hexdigest()


def _bounded(expression):
    return f"CASE WHEN octet_length(({expression})::text)>262144 THEN '{OVERSIZE}' ELSE ({expression})::text END"


_PUBLIC = "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'"
QUERIES = {
    'database': "SELECT pg_encoding_to_char(encoding),datcollate,datctype,datlocprovider,datcollversion,"
        "to_jsonb(d)->>'datlocale',to_jsonb(d)->>'daticulocale',to_jsonb(d)->>'daticurules' "
        "FROM pg_catalog.pg_database d WHERE datname=current_database()",
    'extensions': "SELECT e.extname, e.extversion, n.nspname FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname",
    'relations': "SELECT c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.relreplident,c.reloptions::text,c.relispartition," +
        _bounded("CASE WHEN c.relkind IN ('v','m') THEN pg_get_viewdef(c.oid,false) END") + ',' +
        _bounded("pg_get_expr(c.relpartbound,c.oid,false)") + ',' +
        _bounded("CASE WHEN c.relkind='p' THEN pg_get_partkeydef(c.oid) END") +
        " FROM pg_catalog.pg_class c " + _PUBLIC + " AND c.relkind IN ('r','p','v','m','f','S') ORDER BY c.relname",
    'columns': "SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated," +
        "cn.nspname,co.collname," + _bounded('pg_get_expr(d.adbin,d.adrelid,false)') +
        " FROM pg_catalog.pg_class c JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
        "LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "LEFT JOIN pg_catalog.pg_collation co ON co.oid=a.attcollation "
        "LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid=co.collnamespace " + _PUBLIC +
        # ADD COLUMN appends physically, even when the logical column matches a
        # fresh schema. Named application columns have no positional contract.
        " AND c.relkind IN ('r','p','v','m','f','S') ORDER BY c.relname,a.attname",
    'constraints': "SELECT c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,k.convalidated,k.connoinherit," +
        _bounded('pg_get_constraintdef(k.oid,false)') + " FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_constraint k ON k.conrelid=c.oid " + _PUBLIC + " ORDER BY c.relname,k.conname",
    'indexes': "SELECT c.relname,i.relname,x.indisunique,x.indisprimary,x.indimmediate,x.indisvalid,x.indisready,x.indislive," +
        _bounded('pg_get_indexdef(i.oid)') + " FROM pg_catalog.pg_class c JOIN pg_catalog.pg_index x ON x.indrelid=c.oid "
        "JOIN pg_catalog.pg_class i ON i.oid=x.indexrelid " + _PUBLIC + " ORDER BY c.relname,i.relname",
    'triggers': "SELECT c.relname,CASE WHEN t.tgisinternal THEN NULL ELSE t.tgname END,t.tgisinternal,"
        "t.tgenabled,t.tgtype,t.tgdeferrable,t.tginitdeferred,k.conname,kc.relname,t.tgfoid::regprocedure::text," +
        _bounded("CASE WHEN NOT t.tgisinternal THEN pg_get_triggerdef(t.oid,false) END") +
        " FROM pg_catalog.pg_class c JOIN pg_catalog.pg_trigger t ON t.tgrelid=c.oid "
        "LEFT JOIN pg_catalog.pg_constraint k ON k.oid=t.tgconstraint "
        "LEFT JOIN pg_catalog.pg_class kc ON kc.oid=k.conrelid " + _PUBLIC +
        " ORDER BY c.relname,t.tgisinternal,kc.relname,k.conname,t.tgtype,t.tgname",
    'functions': "SELECT p.oid::regprocedure::text," + _bounded('pg_get_functiondef(p.oid)') +
        " FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.prokind IN ('f','p') AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_depend d "
        "WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e') ORDER BY p.oid::regprocedure::text",
    'routines': "SELECT p.oid::regprocedure::text,p.prokind FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND NOT EXISTS("
        "SELECT 1 FROM pg_catalog.pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e') "
        "ORDER BY p.oid::regprocedure::text",
    'inheritance': "SELECT c.relname,pn.nspname,p.relname,i.inhseqno FROM pg_catalog.pg_inherits i "
        "JOIN pg_catalog.pg_class c ON c.oid=i.inhrelid JOIN pg_catalog.pg_class p ON p.oid=i.inhparent "
        "JOIN pg_catalog.pg_namespace pn ON pn.oid=p.relnamespace " + _PUBLIC + " ORDER BY c.relname,i.inhseqno",
    'policies': "SELECT c.relname,p.polname,p.polcmd,p.polpermissive," + _bounded('pg_get_expr(p.polqual,p.polrelid,false)') + ',' +
        _bounded('pg_get_expr(p.polwithcheck,p.polrelid,false)') + " FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_policy p ON p.polrelid=c.oid " + _PUBLIC + " ORDER BY c.relname,p.polname",
    'sequences': "SELECT sequencename,data_type::text,start_value,min_value,max_value,increment_by,cycle,cache_size "
        "FROM pg_catalog.pg_sequences WHERE schemaname='public' ORDER BY sequencename",
    'types': "SELECT t.typname,t.typtype,format_type(t.typbasetype,t.typtypmod),t.typnotnull," + _bounded('t.typdefault') +
        ",ARRAY(SELECT e.enumlabel FROM pg_catalog.pg_enum e WHERE e.enumtypid=t.oid ORDER BY e.enumsortorder)::text "
        "FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
        "WHERE n.nspname='public' AND t.typtype<>'c' AND t.typelem=0 AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_depend d "
        "WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e') ORDER BY t.typname",
    'versions': 'SELECT version FROM public.tire_schema_versions ORDER BY version',
}


def capture_schema(connection):
    result, size = {}, 0
    for name, query in QUERIES.items():
        rows = []
        previous_streaming = connection.get_execution_options().get('stream_results', False)
        try:
            with connection.execution_options(stream_results=True).execute(text(query + f' LIMIT {MAX_ROWS + 1}')) as cursor:
                for raw in cursor:
                    row = list(raw)
                    if OVERSIZE in row:
                        raise SchemaContractError('schema_capacity')
                    size += len(_json(row))
                    if len(rows) >= MAX_ROWS or size > MAX_BYTES - 4096:
                        raise SchemaContractError('schema_capacity')
                    rows.append(row)
        finally:
            connection.execution_options(stream_results=previous_streaming)
        if name == 'triggers':
            rows.sort(key=_json)  # Internal trigger names contain database-local OIDs.
        result[name] = rows
    _normalize_text_enums(result)
    # This version does not admit tenant-policy-dependent partial views.
    if result['policies'] or any(row[3] or row[4] for row in result['relations']):
        raise SchemaContractError('schema_rls_not_supported')
    if result['types'] or result['inheritance'] or any(row[1] not in ('f','p') for row in result['routines']):
        raise SchemaContractError('schema_feature_not_supported')
    return result


def _normalize_text_enums(catalog):
    # pg_dump can move varchar->text casts from an array to its elements.
    # Admit only parsed literal membership on a separately checked text column.
    from .vehicle_binary_migration import VehicleBinaryMigrationError, _check_expression
    columns = {(row[0], row[1]): row[2] for row in catalog['columns']}
    for row in catalog['constraints']:
        if row[2] != 'c' or not row[-1].startswith('CHECK '):
            continue
        try:
            expression = _check_expression(row[-1][6:])
        except VehicleBinaryMigrationError:
            continue
        if expression[0] != 'in' or expression[1][0] != 'name':
            continue
        column = expression[1][1]
        column_type = columns.get((row[0], column), '')
        if column_type != 'text' and re.fullmatch(r'character varying(?:\(\d+\))?', column_type) is None:
            continue
        row[-1] = 'tire-text-enum@1:' + _json([column, [value[1] for value in expression[2]]]).decode('ascii')


def _settings(connection):
    connection.exec_driver_sql("SET LOCAL search_path=pg_catalog,public")
    connection.exec_driver_sql("SET LOCAL lock_timeout='2s'")
    connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
    connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout='15s'")
    version = int(connection.exec_driver_sql("SELECT current_setting('server_version_num')").scalar())
    if version < 170000:
        raise SchemaContractError('schema_server_unsupported')
    connection.exec_driver_sql('SELECT pg_advisory_xact_lock(821741906)')
    return version // 10000


def load_contract(path, expected_sha256):
    if type(expected_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None:
        raise SchemaContractError('schema_contract_pin_required')
    try:
        path = Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise SchemaContractError('schema_contract_file_invalid')
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if not 1 <= len(data) <= MAX_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise SchemaContractError('schema_contract_hash_mismatch')
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('duplicate')
                value[key] = item
            return value
        contract = json.loads(data.decode('utf-8'), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))
        if (type(contract) is not dict or contract.keys() != {'schema','postgres_major','source_sha256','catalog'}
                or contract['schema'] != SCHEMA or type(contract['postgres_major']) is not int
                or contract['postgres_major'] < 17 or type(contract['catalog']) is not dict
                or contract['catalog'].keys() != QUERIES.keys()):
            raise ValueError('shape')
        for rows in contract['catalog'].values():
            if type(rows) is not list or len(rows) > MAX_ROWS:
                raise ValueError('shape')
            for row in rows:
                if type(row) is not list or any(type(item) not in (str,int,bool,type(None)) for item in row):
                    raise ValueError('shape')
        if contract['source_sha256'] != source_fingerprint():
            raise SchemaContractError('schema_contract_source_changed')
        return contract
    except SchemaContractError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise SchemaContractError('schema_contract_invalid') from None


def verify_schema(engine, path, expected_sha256):
    expected = load_contract(path, expected_sha256)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            major = _settings(connection)
            if major != expected['postgres_major'] or capture_schema(connection) != expected['catalog']:
                raise SchemaContractError('schema_contract_mismatch')
        if expected['source_sha256'] != source_fingerprint():
            raise SchemaContractError('schema_contract_source_changed')
    except SchemaContractError:
        raise
    except Exception:
        raise SchemaContractError('schema_verification_failed') from None


def build_reference(engine, output):
    """Migrate only an empty reference, then publish a new source-bound contract."""
    from .db import register_schema_models, apply_schema
    output = Path(output)
    if not output.is_absolute() or output.is_symlink() or output.exists() or not output.parent.is_dir():
        raise SchemaContractError('schema_contract_output_invalid')
    register_schema_models()
    before = source_fingerprint()
    with engine.begin() as connection:
        major = _settings(connection)
        occupied = connection.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S')) OR EXISTS(SELECT 1 FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND NOT EXISTS(SELECT 1 FROM pg_depend d "
            "WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')) OR EXISTS(SELECT 1 FROM pg_type t "
            "JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' AND t.typtype<>'c' AND t.typelem=0 "
            "AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e'))").scalar()
        if occupied:
            raise SchemaContractError('schema_reference_not_empty')
        # Unqualified CREATE targets the first schema. This is a freshly checked
        # empty reference; runtime/capture keep pg_catalog first for resolution.
        connection.exec_driver_sql('SET LOCAL search_path=public,pg_catalog')
        apply_schema(connection)
        connection.exec_driver_sql('SET LOCAL search_path=pg_catalog,public')
        contract = {'schema': SCHEMA, 'postgres_major': major, 'source_sha256': before, 'catalog': capture_schema(connection)}
        if source_fingerprint() != before:
            raise SchemaContractError('schema_contract_source_changed')
    data = _json(contract)
    if len(data) > MAX_BYTES:
        raise SchemaContractError('schema_capacity')
    with output.open('xb') as stream:
        stream.write(data)
    return {'schema': SCHEMA, 'sha256': hashlib.sha256(data).hexdigest(), 'postgres_major': major,
        'relations': len(contract['catalog']['relations']), 'source_sha256': before}
