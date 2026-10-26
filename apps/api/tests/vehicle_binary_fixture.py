"""Test-owned reader for the fixed, reviewed current023 synthetic fixture.

The predecessor is loaded from committed SQL and fixed expected hashes. No
current metadata, capture builder, gate driver or .artifacts tree is imported.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from sqlalchemy import inspect

FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures/vehicle_binary_023'
FIXTURE_PINS = {
    'schema_023.sql': (85777, '10163a3c2e3f7179c11a6c40ef30fb85da424f902026d28e97c99cd6234007ab'),
    'seed_023.sql': (137518, 'd00cf21e19e8f49b40f5c6d66301e6dec009b8e2b496b04f29c344421ccb2e80'),
    'expected_023.json': (3034106, 'fb57f16c91deed5a4e3963b71ad1698d777659f79b95d52bd1ed5ca2754373f8'),
    'source-index.json': (53664, '9ca4e2e088ffd80fbab926cf4ba4c5972f82896d9a4bc5f7555716bb130f8d8e'),
    'README.md': (1334, '9b6e511d0401686f1aaee74370de12634bdf0ad38423671d21c5b14692097d93'),
}
VERSION_024 = '024_vehicle_binary_raw'
CHANGED_TABLES = {'vehicle_snapshots', 'vehicle_quarantines', 'raw_captures', 'rejected_observations'}
VEHICLE_TABLES = {'vehicle_snapshots', 'vehicle_quarantines'}
NEW_CAPTURE_INDEXES = {f'ix_{table}_raw_capture_id' for table in VEHICLE_TABLES}
SNAPSHOT_INBOUND = {
    ('vehicle_quarantines', 'previous_snapshot_id', 'id'),
    ('vehicle_verifications', 'snapshot_id', 'id'),
    ('vehicle_wheel_fitments', 'snapshot_id', 'id'),
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


def query(connection, statement, parameters=()):
    if hasattr(connection, 'exec_driver_sql'):
        return connection.exec_driver_sql(statement, parameters)
    return connection.execute(statement, parameters)


def cell(value):
    if value is None:
        return {'type': 'null'}
    if isinstance(value, bytes):
        return {'type': 'blob', 'hex': value.hex()}
    if isinstance(value, float):
        assert math.isfinite(value)
        return {'type': 'real', 'value': value}
    return {'type': 'integer' if isinstance(value, int) else 'text', 'value': value}


def rows_digest(connection, table, columns=None, *, where=''):
    selection = '*' if columns is None else ','.join(quoted(name) for name in columns)
    rows = query(connection, 'SELECT ' + selection + ' FROM ' + quoted(table) + where).fetchall()
    typed = sorted(([cell(value) for value in row] for row in rows), key=canonical)
    return {'row_count': len(typed), 'rows_sha256': digest(typed)}


def inventory(connection):
    kinds = {row[1]: row[2] for row in query(connection, 'PRAGMA table_list') if row[0] == 'main'}
    objects = []
    for kind, name, table, sql in query(connection,
            'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name'):
        category = ('shadow' if kinds.get(name) == 'shadow' else 'virtual' if kinds.get(name) == 'virtual'
                    else 'autoindex' if kind == 'index' and sql is None else kind)
        objects.append({'type': kind, 'name': name, 'table': table, 'category': category, 'sql': sql})
    tables = {}
    for item in objects:
        if item['type'] == 'table':
            name = item['name']
            tables[name] = {
                'columns': [list(row) for row in query(connection, 'PRAGMA table_xinfo(' + quoted(name) + ')')],
                'foreign_keys': sorted([list(row) for row in query(connection,
                    'PRAGMA foreign_key_list(' + quoted(name) + ')')]),
                **rows_digest(connection, name),
            }
    versions = [row[0] for row in query(connection, 'SELECT version FROM tire_schema_versions ORDER BY version')]
    return {'schema_objects': objects, 'tables': tables, 'versions': versions}


@lru_cache(maxsize=1)
def fixture_bytes():
    assert {path.name for path in FIXTURE_ROOT.iterdir()} == set(FIXTURE_PINS)
    verified = {}
    for name, (size, sha256) in FIXTURE_PINS.items():
        data = (FIXTURE_ROOT / name).read_bytes()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256, name
        verified[name] = data
    return verified


@lru_cache(maxsize=1)
def fixed_023():
    expected = json.loads(fixture_bytes()['expected_023.json'].decode('utf-8'))
    assert len(expected['inventory']['tables']) == 141
    assert len(expected['inventory']['schema_objects']) == 601
    assert len(expected['inventory']['versions']) == 23
    assert len(expected['private_assets']) == 145
    return expected


@dataclass(frozen=True)
class Private023:
    root: Path
    database: Path
    indexes: dict

    def assert_assets(self):
        assets = fixed_023()['private_assets']
        actual = {path.relative_to(self.root).as_posix() for folder in ('objects', 'bundles')
                  for path in (self.root / folder).rglob('*') if path.is_file()}
        assert actual == set(assets)
        for name, binding in assets.items():
            data = (self.root / name).read_bytes()
            assert len(data) == binding['bytes'] and hashlib.sha256(data).hexdigest() == binding['sha256'], name

    def state(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            return inventory(connection)
        finally:
            connection.close()


def load_private_023(root):
    """Restore only fixed SQL, typed expected and its declared object/bundle bytes."""
    files = fixture_bytes()  # Bind all five bytes before opening the private DB.
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    database = root / 'pre023.sqlite'
    connection = sqlite3.connect(database)
    try:
        connection.executescript(files['schema_023.sql'].decode('utf-8'))
        connection.executescript(files['seed_023.sql'].decode('utf-8'))
        connection.execute('PRAGMA foreign_keys=ON')
        assert connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
        assert inventory(connection) == fixed_023()['inventory']
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        original_indexes = index_contracts(connection)
    finally:
        connection.close()
    private = Private023(root, database, original_indexes)
    for name, binding in fixed_023()['private_assets'].items():
        relative = Path(name)
        assert not relative.is_absolute() and '..' not in relative.parts and relative.as_posix() == name
        assert name.startswith(('objects/sha256/', 'bundles/sha256/'))
        data = base64.b64decode(binding['base64'], validate=True)
        assert len(data) == binding['bytes'] and hashlib.sha256(data).hexdigest() == binding['sha256']
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    private.assert_assets()
    return private


def index_contracts(connection):
    """Read original native index details only from the verified 023 predecessor."""
    result = {}
    tables = [row[0] for row in query(connection, "SELECT name FROM sqlite_schema WHERE type='table'")]
    for table in tables:
        for row in query(connection, 'PRAGMA index_list(' + quoted(table) + ')'):
            # Physical column offsets may move during the declared rebuild;
            # column identity, collation, order and key/auxiliary status may not.
            parts = [(item[0], item[2], item[3], item[4], item[5])
                     for item in query(connection, 'PRAGMA index_xinfo(' + quoted(row[1]) + ')')]
            result[row[1]] = {'table': table, 'unique': row[2], 'origin': row[3], 'partial': row[4],
                              'xinfo': parts}
    return result


def _check_contract(table):
    # Independent handwritten storage contract from the frozen specification;
    # no expected expression is imported from the product migration or models.
    encoding = "body_encoding IN ('utf-8', 'binary')"
    storage = (
        "(body_encoding = 'utf-8' AND body IS NOT NULL AND length(body) > 0 AND content_type = 'application/json') OR "
        "(body_encoding = 'binary' AND body IS NULL AND raw_capture_id IS NOT NULL AND content_type = 'application/pdf' "
        "AND source_id = 'xiaomi-cn-vehicles' AND vehicle_id = 'xiaomi-su7-first-generation')"
    ) if table in VEHICLE_TABLES else (
        "body_encoding = 'utf-8' OR (body_encoding = 'binary' AND source_id = 'xiaomi-cn-vehicles' "
        "AND target_kind = 'vehicle' AND content_type = 'application/pdf')")
    result = {f'ck_{table}_body_encoding': encoding, f'ck_{table}_body_storage': storage}
    if table == 'raw_captures':
        result['ck_raw_captures_byte_count'] = ("typeof(raw_body) = 'blob' AND byte_count >= 1 AND "
            'byte_count <= 8388608 AND byte_count = length(raw_body)')
    return result


def _normal_check(sql):
    # Preserve literal case and every grouping parenthesis.
    pieces = re.split(r"('(?:''|[^'])*')", sql)
    return ''.join(piece if number % 2 else re.sub(r'\s+', '', piece).replace('"', '').upper()
                   for number, piece in enumerate(pieces))


def assert_024_delta(connection, original_indexes):
    """Only handwritten 024 differences are allowed over the fixed old inventory."""
    old = fixed_023()['inventory']
    current = inventory(connection)
    actual_indexes = index_contracts(connection)
    assert set(actual_indexes) == set(original_indexes) | NEW_CAPTURE_INDEXES
    for name, contract in original_indexes.items():
        assert actual_indexes[name] == contract, name
    for table in CHANGED_TABLES:
        reflected = inspect(connection).get_check_constraints(table)
        actual_checks = {item['name']: _normal_check(item['sqltext']) for item in reflected}
        assert len(reflected) == len(actual_checks) == len(_check_contract(table)), table
        assert actual_checks == {name: _normal_check(sql) for name, sql in _check_contract(table).items()}, table
    assert current['versions'] == old['versions'] + [VERSION_024]
    assert set(current['tables']) == set(old['tables'])
    before = {(item['type'], item['name']): item for item in old['schema_objects']}
    after = {(item['type'], item['name']): item for item in current['schema_objects']}
    assert set(after) - set(before) == {('index', name) for name in NEW_CAPTURE_INDEXES}
    assert not set(before) - set(after)
    for key, item in before.items():
        if not (item['type'] == 'table' and item['name'] in CHANGED_TABLES):
            assert after[key] == item, key
    for table, expected in old['tables'].items():
        actual = current['tables'][table]
        columns = [list(column) for column in expected['columns']]
        if table in CHANGED_TABLES:
            if table in VEHICLE_TABLES:
                next(column for column in columns if column[1] == 'body')[3] = 0
            columns.append([len(columns), 'body_encoding', 'VARCHAR(16)', 1, "'utf-8'", 0, 0])
            if table in VEHICLE_TABLES:
                columns.append([len(columns), 'raw_capture_id', 'VARCHAR(64)', 0, None, 0, 0])
        if table in CHANGED_TABLES:
            # Rebuilding may place the two declared new columns beside body;
            # every old column property and every added property is still fixed.
            assert {column[1]: column[2:] for column in actual['columns']} == {
                column[1]: column[2:] for column in columns}, table
        else:
            assert actual['columns'] == columns, table
        # SQLite renumbers FK ids when the additional FK is declared; compare
        # each complete relation including composite sequence and ON DELETE.
        fks = sorted(tuple(row[1:]) for row in expected['foreign_keys'])
        if table in VEHICLE_TABLES:
            fks.append((0, 'raw_captures', 'raw_capture_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE'))
        assert sorted(tuple(row[1:]) for row in actual['foreign_keys']) == sorted(fks), table
        old_columns = [column[1] for column in expected['columns'] if column[6] == 0]
        projection = rows_digest(connection, table, old_columns,
            where=" WHERE version != '024_vehicle_binary_raw'" if table == 'tire_schema_versions' else '')
        assert projection == {key: expected[key] for key in ('row_count', 'rows_sha256')}, table
        if table in CHANGED_TABLES:
            assert query(connection, 'SELECT DISTINCT body_encoding FROM ' + quoted(table)).fetchall() == [('utf-8',)]
        if table in VEHICLE_TABLES:
            assert query(connection, 'SELECT COUNT(*) FROM ' + quoted(table) + ' WHERE raw_capture_id IS NOT NULL').fetchone()[0] == 0
    inbound = {(table, fk[3], fk[4]) for table, info in current['tables'].items()
               for fk in info['foreign_keys'] if fk[2] == 'vehicle_snapshots'}
    assert inbound == SNAPSHOT_INBOUND
    assert not any(fk[2] == 'vehicle_quarantines' for info in current['tables'].values() for fk in info['foreign_keys'])
    for table in VEHICLE_TABLES:
        index_name = 'ix_' + table + '_raw_capture_id'
        indexes = {row[1]: row for row in query(connection, 'PRAGMA index_list(' + quoted(table) + ')')}
        assert indexes[index_name][2] == 0  # multiple observations may share a capture
        assert actual_indexes[index_name] == {'table': table, 'unique': 0, 'origin': 'c', 'partial': 0,
            'xinfo': [(0, 'raw_capture_id', 0, 'BINARY', 1), (1, None, 0, 'BINARY', 0)]}
        assert [row[2] for row in query(connection, 'PRAGMA index_info(' + quoted(index_name) + ')')] == ['raw_capture_id']
    assert query(connection, 'PRAGMA foreign_key_check').fetchall() == []
    assert query(connection, 'PRAGMA integrity_check').fetchall() == [('ok',)]
